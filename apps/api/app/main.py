from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from app.api.ws_chat import router as ws_router
from app.api.traces import router as traces_router
from app.api.sessions import router as sessions_router
from app.api.auth import router as auth_router
from app.api.memory import router as memory_router
from app.api.reminder_api import router as reminder_api_router
from app.api.caretasks import router as caretasks_router
from app.api.tool_execute import router as tool_execute_router
from app.api.asr import router as asr_router
from app.api.tts import router as tts_router
from app.api.devices import router as devices_router
from app.api.ws_device_realtime import router as ws_device_realtime_router
from app.api.alerts import router as alerts_router
from app.api.carecircle import router as carecircle_router
from app.api.contacts import router as contacts_router
from app.api.households import router as households_router
from app.api.platform import router as platform_router
from app.observability.logger import setup_logging
from app.observability.trace_service import setup_otel

import logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    setup_otel()
    from app.config.settings import settings
    settings.validate_security()
    from app.engines.risk_engine import RiskEngine
    RiskEngine()
    logger.info("Companion Runtime started")
    yield
    logger.info("Companion Runtime shutting down")


app = FastAPI(title="AI Companion Runtime", version="0.1.0", lifespan=lifespan)

from app.config.settings import settings as _settings  # noqa: E402
from app.api.rate_limiter import RateLimitMiddleware  # noqa: E402

_cors_origins = [o.strip() for o in _settings.cors_allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)

# Mount Prometheus metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

app.include_router(ws_router)
app.include_router(ws_device_realtime_router)
app.include_router(traces_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(memory_router, prefix="/api")
app.include_router(reminder_api_router, prefix="/api")
app.include_router(caretasks_router, prefix="/api")
app.include_router(tool_execute_router, prefix="/api")
app.include_router(alerts_router, prefix="/api")
app.include_router(devices_router, prefix="/api")
app.include_router(households_router, prefix="/api")
app.include_router(carecircle_router, prefix="/api")
app.include_router(contacts_router, prefix="/api")
app.include_router(platform_router, prefix="/api")
app.include_router(asr_router)
app.include_router(tts_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def readiness():
    from fastapi.responses import JSONResponse
    from app.runtime.readiness import assess_platform_readiness, readiness_http_status

    payload = await assess_platform_readiness()
    return JSONResponse(
        status_code=readiness_http_status(payload),
        content=payload,
    )
