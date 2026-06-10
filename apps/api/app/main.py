from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from app.api.ws_chat import router as ws_router
from app.api.traces import router as traces_router
from app.api.sessions import router as sessions_router
from app.api.auth import router as auth_router
from app.api.memory import router as memory_router
from app.observability.logger import setup_logging
from app.observability.trace_service import setup_otel

import logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    setup_otel()
    logger.info("Companion Runtime started")
    yield
    logger.info("Companion Runtime shutting down")


app = FastAPI(title="AI Companion Runtime", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Prometheus metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

app.include_router(ws_router)
app.include_router(traces_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(memory_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
