from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

from sqlalchemy import text

from app.config.settings import Settings, settings

READY = "ready"
DEGRADED = "degraded"
UNSAFE = "unsafe_to_serve"

CheckFunc = Callable[[Settings], Awaitable["ReadinessCheck"]]


@dataclass(frozen=True)
class ReadinessCheck:
    status: str
    detail: str
    observed: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status, "detail": self.detail}
        if self.observed:
            payload["observed"] = self.observed
        return payload


def _is_production(app_settings: Settings) -> bool:
    return app_settings.app_env.lower() == "production"


def _split_csv(value: str) -> list[str]:
    return sorted(item.strip() for item in value.split(",") if item.strip())


def _redis_url_with_password(url: str, password: str) -> str:
    if not password:
        return url
    parsed = urlparse(url)
    if parsed.password or parsed.username:
        return url
    netloc = f":{quote(password, safe='')}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


async def check_public_api_ws_config(app_settings: Settings) -> ReadinessCheck:
    api_url = app_settings.public_api_url.strip()
    ws_url = app_settings.public_ws_url.strip()
    observed = {
        "public_api_url_configured": bool(api_url),
        "public_ws_url_configured": bool(ws_url),
    }
    if _is_production(app_settings):
        failures: list[str] = []
        if not api_url:
            failures.append("PUBLIC_API_URL is not set")
        elif not api_url.startswith("https://"):
            failures.append("PUBLIC_API_URL must use https")
        if not ws_url:
            failures.append("PUBLIC_WS_URL is not set")
        elif not ws_url.startswith("wss://"):
            failures.append("PUBLIC_WS_URL must use wss")
        if failures:
            return ReadinessCheck(UNSAFE, "; ".join(failures), observed)
    if not api_url or not ws_url:
        return ReadinessCheck(DEGRADED, "explicit public API/WS URLs are not fully configured", observed)
    return ReadinessCheck(READY, "explicit public API/WS URLs are configured", observed)


async def check_risk_policy(app_settings: Settings) -> ReadinessCheck:
    try:
        from app.engines.risk_engine import RiskEngine

        RiskEngine()
    except Exception as exc:
        return ReadinessCheck(UNSAFE, "risk policy could not initialize", {"error": repr(exc)})
    return ReadinessCheck(READY, "risk policy initialized")


async def check_database(app_settings: Settings) -> ReadinessCheck:
    try:
        from app.db.session import async_session

        async with async_session() as db:
            await db.execute(text("SELECT 1"))
    except Exception as exc:
        return ReadinessCheck(UNSAFE, "database is unavailable", {"error": repr(exc)})
    return ReadinessCheck(READY, "database responded")


async def check_redis(app_settings: Settings) -> ReadinessCheck:
    try:
        from app.storage.redis_client import get_redis

        redis = await get_redis()
        await redis.ping()
    except Exception as exc:
        return ReadinessCheck(UNSAFE, "redis is unavailable", {"error": repr(exc)})
    return ReadinessCheck(READY, "redis responded")


async def check_migration_heads(app_settings: Settings) -> ReadinessCheck:
    expected = _split_csv(app_settings.expected_migration_heads)
    if not expected:
        status = UNSAFE if _is_production(app_settings) else DEGRADED
        return ReadinessCheck(status, "EXPECTED_MIGRATION_HEADS is not configured")

    try:
        from app.db.session import async_session

        async with async_session() as db:
            result = await db.execute(text("SELECT version_num FROM alembic_version"))
            observed = sorted(row[0] for row in result.fetchall())
    except Exception as exc:
        return ReadinessCheck(
            UNSAFE,
            "migration DB heads could not be read",
            {"expected": expected, "error": repr(exc)},
        )

    if observed != expected:
        return ReadinessCheck(
            UNSAFE,
            "migration DB heads do not match EXPECTED_MIGRATION_HEADS",
            {"expected": expected, "observed": observed},
        )
    return ReadinessCheck(READY, "migration DB heads match expected heads", {"heads": observed})


async def check_notification_provider(app_settings: Settings) -> ReadinessCheck:
    provider = (app_settings.notification_provider or "").strip().lower()
    if provider in {"", "unconfigured", "sandbox"}:
        status = UNSAFE if _is_production(app_settings) else DEGRADED
        return ReadinessCheck(
            status,
            "notification provider is not production-capable",
            {"provider": provider or "unconfigured"},
        )
    if provider == "signed_webhook" and _is_production(app_settings):
        failures: list[str] = []
        if not app_settings.notification_outbound_url.startswith("https://"):
            failures.append("NOTIFICATION_OUTBOUND_URL must use https")
        if not app_settings.notification_webhook_secret.strip():
            failures.append("NOTIFICATION_WEBHOOK_SECRET is not set")
        if failures:
            return ReadinessCheck(
                UNSAFE,
                "; ".join(failures),
                {"provider": provider},
            )
    return ReadinessCheck(READY, "notification provider is production-capable", {"provider": provider})


async def check_device_identity(app_settings: Settings) -> ReadinessCheck:
    observed = {
        "device_identity_required": app_settings.device_identity_required,
        "public_ws_url_configured": bool(app_settings.public_ws_url.strip()),
    }
    if _is_production(app_settings):
        if not app_settings.device_identity_required:
            return ReadinessCheck(UNSAFE, "device identity enforcement is disabled", observed)
        if not app_settings.public_ws_url.startswith("wss://"):
            return ReadinessCheck(UNSAFE, "device WebSocket transport must use wss", observed)
    if not app_settings.device_identity_required:
        return ReadinessCheck(DEGRADED, "device identity enforcement is disabled", observed)
    return ReadinessCheck(READY, "device identity enforcement is configured", observed)


async def check_worker_broker_and_heartbeat(app_settings: Settings) -> ReadinessCheck:
    if not app_settings.enable_celery_tasks:
        status = UNSAFE if _is_production(app_settings) else DEGRADED
        return ReadinessCheck(status, "Celery workers are disabled")

    try:
        import redis.asyncio as redis

        broker_url = _redis_url_with_password(
            app_settings.celery_broker_url,
            app_settings.redis_password,
        )
        broker = redis.from_url(broker_url)
        try:
            await broker.ping()
        finally:
            await broker.aclose()

        redis_url = _redis_url_with_password(app_settings.redis_url, app_settings.redis_password)
        redis_client = redis.from_url(redis_url)
        try:
            raw_value = await redis_client.get(app_settings.platform_worker_heartbeat_key)
        finally:
            await redis_client.aclose()
    except Exception as exc:
        return ReadinessCheck(UNSAFE, "worker broker is unavailable", {"error": repr(exc)})

    if raw_value is None:
        return ReadinessCheck(UNSAFE, "worker heartbeat is missing")

    try:
        heartbeat_at = float(raw_value)
    except (TypeError, ValueError):
        return ReadinessCheck(UNSAFE, "worker heartbeat is malformed")

    age_seconds = time.time() - heartbeat_at
    observed = {"heartbeat_age_seconds": round(age_seconds, 3)}
    if age_seconds > app_settings.platform_worker_heartbeat_max_age_seconds:
        return ReadinessCheck(UNSAFE, "worker heartbeat is stale", observed)
    return ReadinessCheck(READY, "worker broker and heartbeat are healthy", observed)


DEFAULT_CHECKS: tuple[tuple[str, CheckFunc], ...] = (
    ("public_api_ws_config", check_public_api_ws_config),
    ("risk_policy", check_risk_policy),
    ("database", check_database),
    ("redis", check_redis),
    ("migration_heads", check_migration_heads),
    ("notification_provider", check_notification_provider),
    ("device_identity", check_device_identity),
    ("worker_heartbeat", check_worker_broker_and_heartbeat),
)


async def assess_platform_readiness(
    app_settings: Settings = settings,
    checks: tuple[tuple[str, CheckFunc], ...] = DEFAULT_CHECKS,
) -> dict[str, Any]:
    results: dict[str, ReadinessCheck] = {}
    for name, check in checks:
        results[name] = await check(app_settings)

    statuses = {result.status for result in results.values()}
    if UNSAFE in statuses:
        status = UNSAFE
    elif DEGRADED in statuses:
        status = DEGRADED
    else:
        status = READY

    return {
        "scope": "platform",
        "status": status,
        "checks": {name: result.as_dict() for name, result in results.items()},
    }


def readiness_http_status(readiness: dict[str, Any]) -> int:
    return 503 if readiness["status"] == UNSAFE else 200
