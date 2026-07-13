import hashlib
import json
import logging
import re
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

_TOOL_SEMANTIC_KEYS = {
    "action", "status", "delivery_status", "entity_id", "task_id", "receipt_id",
    "transition", "before", "after", "schedule_type", "operation", "reason",
    "error_code", "error_class", "index", "expected_version", "current_version",
}


_REDACTED_FINGERPRINT = re.compile(r"redacted:[0-9a-f]{12}")
_JWT_LIKE = re.compile(r"[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{8,}")
_GOOGLE_TOKEN = re.compile(r"AQ\.?[A-Za-z0-9_-]{20,}")
_COMMON_SECRET = re.compile(
    r"(?:sk-|gh[pousr]_|github_pat_|AKIA|ASIA|AIza|ya29\.|xox[baprs]-|key-)[A-Za-z0-9_.-]{8,}",
    re.IGNORECASE,
)


def _redacted_fingerprint(raw: str) -> str:
    return f"redacted:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]}"


def _looks_secret(raw: str) -> bool:
    lowered = raw.lower()
    return (
        bool(_JWT_LIKE.search(raw))
        or bool(_GOOGLE_TOKEN.search(raw))
        or bool(_COMMON_SECRET.search(raw))
        or any(
            marker in lowered
            for marker in ("secret", "token", "password", "credential", "bearer", "private_key")
        )
        or lowered.startswith(("http://", "https://"))
    )


def _semantic_token(value: object, *, limit: int = 80) -> str | int | float | bool | None:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raw = str(value).strip()
    if _REDACTED_FINGERPRINT.fullmatch(raw):
        return raw
    if _looks_secret(raw):
        return _redacted_fingerprint(raw)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,79}", raw):
        return raw[:limit]
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        return _redacted_fingerprint(raw)


def _semantic_field(key: str, value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raw = str(value).strip()
    if _REDACTED_FINGERPRINT.fullmatch(raw):
        return raw
    if _looks_secret(raw):
        return _redacted_fingerprint(raw)
    if key.endswith("_id"):
        try:
            return str(uuid.UUID(raw))
        except ValueError:
            return _redacted_fingerprint(raw)
    if key == "action" and (
        raw in {"create", "list", "complete", "snooze", "cancel", "batch", "note", "recall"}
        or re.fullmatch(r"(?:caretask|contact|memory|reminder)_[a-z0-9_]{1,60}", raw)
    ):
        return raw
    if key in {"status", "delivery_status", "before", "after", "transition"} and raw in {
        "success", "failed", "timeout", "needs_clarification", "pending", "persisted",
        "queued", "completed", "unattempted", "cancelled", "running", "claimed",
        "refused", "unauthorized", "delivered", "read", "acknowledged", "no_contact",
        "no_verified_contact", "recorded", "active", "due", "done", "snoozed", "missed",
    }:
        return raw
    if key == "schedule_type" and raw in {"once", "daily", "weekly", "interval"}:
        return raw
    if key == "error_class" and re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,60}(?:Error|Exception)", raw):
        return raw
    if key in {"error_code", "reason", "operation"} and raw in {
        "tool_timeout", "tool_execution_failed", "bridge_unreachable", "bridge_http_error",
        "risk_blocked", "caretask_execution_failed", "mutation_not_authorized",
        "ambiguous_mutation_cues", "unplanned_mutation_cue", "consent_required",
        "not_found", "invalid_transition", "missing_user", "idempotency_conflict",
    }:
        return raw
    return _semantic_token(raw)


def sanitize_tool_evidence(payload: object) -> dict:
    """Return bounded semantic evidence without persisting caller-controlled content."""
    try:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        serialized = type(payload).__name__
    evidence: dict = {
        "content_redacted": True,
        "content_chars": min(len(serialized), 1_000_000),
        "content_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    }
    if isinstance(payload, dict) and payload.get("content_redacted") is True:
        fingerprint = payload.get("content_sha256")
        chars = payload.get("content_chars")
        if isinstance(fingerprint, str) and re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            evidence["content_sha256"] = fingerprint
        if isinstance(chars, int):
            evidence["content_chars"] = min(max(chars, 0), 1_000_000)

    def collect(value: object) -> None:
        if not isinstance(value, dict):
            return
        for key, item in value.items():
            if key in _TOOL_SEMANTIC_KEYS and key not in evidence:
                evidence[key] = _semantic_field(key, item)
        receipts = value.get("receipts")
        if isinstance(receipts, list):
            evidence["receipts"] = [
                {
                    key: _semantic_field(key, item[key])
                    for key in _TOOL_SEMANTIC_KEYS
                    if key in item
                }
                for item in receipts[:20]
                if isinstance(item, dict)
            ]
            evidence["receipts_truncated"] = len(receipts) > 20
        for key in ("params", "data"):
            collect(value.get(key))

    collect(payload)
    return evidence


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
    except Exception as exc:
        logger.warning(
            "OpenTelemetry setup skipped error_class=%s code=otel_setup_failed",
            type(exc).__name__,
        )


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
        except Exception as exc:
            logger.error(
                "Trace event persistence failed error_class=%s code=trace_event_persist_failed",
                type(exc).__name__,
            )
            if required:
                raise AuditPersistenceError("Failed to persist critical audit event") from exc

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
        except Exception as exc:
            logger.error(
                "Model call persistence failed error_class=%s code=model_call_persist_failed",
                type(exc).__name__,
            )

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
                    input_json=sanitize_tool_evidence(input_json),
                    output_json=sanitize_tool_evidence(output_json),
                    status=status,
                    latency_ms=latency_ms,
                )
                db.add(call)
                await db.commit()
        except Exception as exc:
            logger.error(
                "Tool call persistence failed tool=%s error_class=%s code=tool_call_persist_failed",
                _semantic_token(tool_name),
                type(exc).__name__,
            )

    async def get_trace(self, trace_id: str) -> Optional[dict]:
        try:
            from app.db.session import async_session
            from app.db.models import Message, TraceEvent, ModelCall, ToolCall
            from sqlalchemy import select

            async with async_session() as db:
                # Events
                events_result = await db.execute(
                    select(TraceEvent)
                    .where(TraceEvent.trace_id == trace_id)
                    .order_by(
                        TraceEvent.step_index,
                        TraceEvent.created_at,
                        TraceEvent.id,
                    )
                )
                events = events_result.scalars().all()

                # Model calls
                model_result = await db.execute(
                    select(ModelCall).where(ModelCall.trace_id == trace_id)
                )
                model_calls = model_result.scalars().all()

                # Tool calls
                tool_result = await db.execute(
                    select(ToolCall)
                    .where(ToolCall.trace_id == trace_id)
                    .order_by(ToolCall.created_at, ToolCall.id)
                )
                tool_calls = tool_result.scalars().all()

                message_result = await db.execute(
                    select(Message)
                    .where(Message.trace_id == trace_id)
                    .order_by(Message.message_index, Message.created_at, Message.id)
                )
                messages = message_result.scalars().all()

            if not events and not messages and not tool_calls:
                return None

            first = events[0] if events else None
            last = events[-1] if events else None
            first_message = messages[0] if messages else None

            total_tokens = sum((mc.prompt_tokens or 0) + (mc.output_tokens or 0) for mc in model_calls)
            total_cost = sum(mc.cost_cents or 0 for mc in model_calls)

            return {
                "trace_id": trace_id,
                "user_id": str(first.user_id) if first and first.user_id else (
                    str(first_message.user_id) if first_message else None
                ),
                "session_id": str(first.session_id) if first and first.session_id else (
                    str(first_message.session_id) if first_message else None
                ),
                "started_at": first.start_time.isoformat() if first and first.start_time else (
                    first_message.created_at.isoformat()
                    if first_message and first_message.created_at else None
                ),
                "total_latency_ms": last.latency_ms if last else None,
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
                "messages": [
                    {
                        "id": str(message.id),
                        "role": message.role,
                        "content": message.content,
                        "message_index": message.message_index,
                        "created_at": message.created_at.isoformat()
                        if message.created_at else None,
                    }
                    for message in messages
                ],
                "cost_summary": {
                    "total_tokens": total_tokens,
                    "total_cost_cents": round(total_cost, 4),
                },
            }
        except Exception as exc:
            logger.error(
                "Trace read failed error_class=%s code=trace_read_failed",
                type(exc).__name__,
            )
            return None
