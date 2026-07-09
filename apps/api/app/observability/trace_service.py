import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AuditPersistenceError(RuntimeError):
    """A required domain audit event could not be persisted."""


def setup_otel():
    """Initialize OpenTelemetry. Best-effort."""
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from app.config.settings import settings

        resource = Resource.create({"service.name": settings.otel_service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        logger.info("OpenTelemetry initialized")
    except Exception as e:
        logger.warning(f"OpenTelemetry setup skipped: {e}")


class TraceService:
    """Records trace events to PostgreSQL."""

    async def add_event(
        self,
        trace_id: str,
        step_name: str,
        step_index: int,
        user_id: str = None,
        session_id: str = None,
        input_json: dict = None,
        output_json: dict = None,
        status: str = "success",
        error_message: str = None,
        latency_ms: int = None,
        required: bool = False,
    ):
        try:
            from app.db.session import async_session
            from app.db.models import TraceEvent
            from datetime import datetime

            async with async_session() as db:
                event = TraceEvent(
                    trace_id=trace_id,
                    user_id=user_id,
                    session_id=session_id,
                    step_name=step_name,
                    step_index=step_index,
                    input_json=input_json,
                    output_json=output_json,
                    status=status,
                    error_message=error_message,
                    latency_ms=latency_ms,
                    start_time=datetime.utcnow(),
                    end_time=datetime.utcnow(),
                    created_at=datetime.utcnow(),
                )
                db.add(event)
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to record trace event: {e}")
            if required:
                raise AuditPersistenceError("Failed to persist critical audit event") from e

    async def record_model_call(
        self,
        trace_id: str,
        provider: str,
        model: str,
        role: str,
        prompt_tokens: int = 0,
        output_tokens: int = 0,
        ttft_ms: int = 0,
        total_latency_ms: int = 0,
        status: str = "success",
        error_message: str = None,
    ):
        try:
            from app.db.session import async_session
            from app.db.models import ModelCall
            from app.observability.cost_tracker import calculate_cost

            cost = calculate_cost(model, prompt_tokens, output_tokens)

            async with async_session() as db:
                call = ModelCall(
                    trace_id=trace_id,
                    provider=provider,
                    model=model,
                    role=role,
                    prompt_tokens=prompt_tokens,
                    output_tokens=output_tokens,
                    ttft_ms=ttft_ms,
                    total_latency_ms=total_latency_ms,
                    status=status,
                    error_message=error_message,
                    cost_cents=cost,
                )
                db.add(call)
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to record model call: {e}")

    async def record_tool_call(
        self,
        trace_id: str,
        tool_name: str,
        input_json: dict = None,
        output_json: dict = None,
        status: str = "success",
        latency_ms: int = 0,
    ):
        try:
            from app.db.session import async_session
            from app.db.models import ToolCall

            async with async_session() as db:
                call = ToolCall(
                    trace_id=trace_id,
                    tool_name=tool_name,
                    input_json=input_json,
                    output_json=output_json,
                    status=status,
                    latency_ms=latency_ms,
                )
                db.add(call)
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to record tool call: {e}")

    async def get_trace(self, trace_id: str) -> Optional[dict]:
        try:
            from app.db.session import async_session
            from app.db.models import TraceEvent, ModelCall, ToolCall
            from sqlalchemy import select

            async with async_session() as db:
                # Events
                events_result = await db.execute(
                    select(TraceEvent)
                    .where(TraceEvent.trace_id == trace_id)
                    .order_by(TraceEvent.step_index)
                )
                events = events_result.scalars().all()

                # Model calls
                model_result = await db.execute(
                    select(ModelCall).where(ModelCall.trace_id == trace_id)
                )
                model_calls = model_result.scalars().all()

                # Tool calls
                tool_result = await db.execute(
                    select(ToolCall).where(ToolCall.trace_id == trace_id)
                )
                tool_calls = tool_result.scalars().all()

            if not events:
                return None

            first = events[0]
            last = events[-1]

            total_tokens = sum((mc.prompt_tokens or 0) + (mc.output_tokens or 0) for mc in model_calls)
            total_cost = sum(mc.cost_cents or 0 for mc in model_calls)

            return {
                "trace_id": trace_id,
                "user_id": str(first.user_id) if first.user_id else None,
                "session_id": str(first.session_id) if first.session_id else None,
                "started_at": first.start_time.isoformat() if first.start_time else None,
                "total_latency_ms": last.latency_ms,
                "events": [
                    {
                        "step_name": e.step_name,
                        "step_index": e.step_index,
                        "status": e.status,
                        "latency_ms": e.latency_ms,
                        "input": e.input_json,
                        "output": e.output_json,
                        "error": e.error_message,
                    }
                    for e in events
                ],
                "model_calls": [
                    {
                        "provider": mc.provider,
                        "model": mc.model,
                        "role": mc.role,
                        "prompt_tokens": mc.prompt_tokens,
                        "output_tokens": mc.output_tokens,
                        "ttft_ms": mc.ttft_ms,
                        "total_latency_ms": mc.total_latency_ms,
                        "status": mc.status,
                        "cost_cents": mc.cost_cents,
                    }
                    for mc in model_calls
                ],
                "tool_calls": [
                    {
                        "tool_name": tc.tool_name,
                        "status": tc.status,
                        "latency_ms": tc.latency_ms,
                        "input": tc.input_json,
                        "output": tc.output_json,
                    }
                    for tc in tool_calls
                ],
                "cost_summary": {
                    "total_tokens": total_tokens,
                    "total_cost_cents": round(total_cost, 4),
                },
            }
        except Exception as e:
            logger.error(f"Failed to get trace: {e}")
            return None
