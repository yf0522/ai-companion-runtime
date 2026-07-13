from __future__ import annotations

import asyncio
import logging
import math
import re
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

from sqlalchemy import text

from app.config.settings import Settings, settings

READY = "ready"
DEGRADED = "degraded"
UNSAFE = "unsafe_to_serve"

PUBLIC_CONTRACT_VERSION = "platform-readiness.v1"
OPERATOR_CONTRACT_VERSION = "operator-platform-readiness.v1"
_CANONICAL_STATUSES = frozenset({READY, DEGRADED, UNSAFE})
_UNKNOWN_METRIC_LABEL = "unknown"
_CONFIGURATION_CHECK_ID = "readiness_configuration"
_URL_CREDENTIALS = re.compile(r"([a-z][a-z0-9+.-]*://)([^/@\s]+)@", re.IGNORECASE)
_AUTHORIZATION_VALUE = re.compile(
    r"\b(authorization|proxy-authorization)[\"']?\s*[:=]\s*[\"']?"
    r"(?:(?:bearer|basic|api[-_]?key)\s+)?[^\s,;\"']+",
    re.IGNORECASE,
)
_AUTH_SCHEME_VALUE = re.compile(
    r"\b(bearer|basic|api[-_]?key)\s+[^\s,;\"']+",
    re.IGNORECASE,
)
_API_KEY_HEADER_VALUE = re.compile(
    r"\b([a-z0-9_-]*api[-_]?key)[\"']?\s*[:=]\s*[\"']?[^\s,;\"']+",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT = re.compile(
    r"\b(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)

CheckFunc = Callable[[Settings], Awaitable["ReadinessCheck"]]


@dataclass(frozen=True)
class ObservedField:
    kind: str
    max_length: int = 80
    max_items: int = 20


@dataclass(frozen=True)
class CheckCatalogEntry:
    label: str
    owner: str
    next_action: str
    runbook: str
    observed_fields: tuple[tuple[str, ObservedField], ...] = ()


CHECK_CATALOG: Mapping[str, CheckCatalogEntry] = MappingProxyType(
    {
        "public_api_ws_config": CheckCatalogEntry(
            label="Public API and WebSocket configuration",
            owner="Platform runtime",
            next_action="Verify the public HTTPS and WSS endpoint configuration.",
            runbook="platform-readiness#public-api-ws-config",
            observed_fields=(
                ("public_api_url_configured", ObservedField("bool")),
                ("public_ws_url_configured", ObservedField("bool")),
            ),
        ),
        "risk_policy": CheckCatalogEntry(
            label="Safety risk policy",
            owner="Safety engineering",
            next_action="Validate that the packaged risk rules can initialize.",
            runbook="platform-readiness#risk-policy",
        ),
        "database": CheckCatalogEntry(
            label="Primary database",
            owner="Platform runtime",
            next_action="Verify database reachability, credentials, and connection capacity.",
            runbook="platform-readiness#database",
        ),
        "vector_schema": CheckCatalogEntry(
            label="pgvector embedding schema",
            owner="Platform runtime",
            next_action="Verify the vector extension and memory embedding column schema.",
            runbook="platform-readiness#vector-schema",
            observed_fields=(
                ("extension_installed", ObservedField("bool")),
                ("embedding_type", ObservedField("string", max_length=32)),
                ("index_exists", ObservedField("bool")),
                ("index_method", ObservedField("string", max_length=16)),
                ("index_opclass", ObservedField("string", max_length=32)),
                ("index_table", ObservedField("string", max_length=64)),
                ("index_column", ObservedField("string", max_length=64)),
                ("index_valid", ObservedField("bool")),
                ("index_ready", ObservedField("bool")),
            ),
        ),
        "redis": CheckCatalogEntry(
            label="Redis memory and queue store",
            owner="Platform runtime",
            next_action="Verify the active Redis URL and authentication profile.",
            runbook="platform-readiness#redis",
        ),
        "migration_heads": CheckCatalogEntry(
            label="Database migration heads",
            owner="Release engineering",
            next_action="Compare deployed and expected Alembic migration heads.",
            runbook="platform-readiness#migration-heads",
            observed_fields=(
                ("expected", ObservedField("string_list")),
                ("observed", ObservedField("string_list")),
                ("heads", ObservedField("string_list")),
            ),
        ),
        "notification_provider": CheckCatalogEntry(
            label="Notification delivery provider",
            owner="Care operations",
            next_action="Verify the configured provider and its delivery credentials.",
            runbook="platform-readiness#notification-provider",
            observed_fields=(("provider", ObservedField("string")),),
        ),
        "device_identity": CheckCatalogEntry(
            label="Companion device identity",
            owner="Device security",
            next_action="Verify device identity enforcement and secure WebSocket transport.",
            runbook="platform-readiness#device-identity",
            observed_fields=(
                ("device_identity_required", ObservedField("bool")),
                ("public_ws_url_configured", ObservedField("bool")),
            ),
        ),
        "worker_heartbeat": CheckCatalogEntry(
            label="Worker broker and heartbeat",
            owner="Platform runtime",
            next_action="Verify the broker connection and the latest worker heartbeat.",
            runbook="platform-readiness#worker-heartbeat",
            observed_fields=(("heartbeat_age_seconds", ObservedField("number")),),
        ),
    }
)
REQUIRED_CHECK_IDS = tuple(CHECK_CATALOG)


@dataclass(frozen=True)
class ReadinessCheck:
    status: str
    detail: str
    observed: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    def as_dict(self, check_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "detail": _safe_text(self.detail, fallback="readiness state unavailable"),
            "duration_ms": _safe_duration_ms(self.duration_ms),
        }
        observed = _sanitize_observed(check_id, self.observed)
        if observed:
            payload["observed"] = observed
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


def _safe_text(value: Any, *, fallback: str, max_length: int = 240) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = " ".join(value.split())
    if not cleaned:
        return fallback
    cleaned = _URL_CREDENTIALS.sub(r"\1[redacted]@", cleaned)
    cleaned = _AUTHORIZATION_VALUE.sub(r"\1: [redacted]", cleaned)
    cleaned = _API_KEY_HEADER_VALUE.sub(r"\1: [redacted]", cleaned)
    cleaned = _AUTH_SCHEME_VALUE.sub(r"\1 [redacted]", cleaned)
    cleaned = _SECRET_ASSIGNMENT.sub(r"\1=[redacted]", cleaned)
    return cleaned[:max_length]


def _safe_duration_ms(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        return 0.0
    return round(numeric, 3)


def _sanitize_observed(check_id: str | None, observed: Any) -> dict[str, Any]:
    catalog_entry = CHECK_CATALOG.get(check_id or "")
    if catalog_entry is None or not isinstance(observed, dict):
        return {}

    sanitized: dict[str, Any] = {}
    for key, contract in catalog_entry.observed_fields:
        if key not in observed:
            continue
        value = observed[key]
        if contract.kind == "bool" and isinstance(value, bool):
            sanitized[key] = value
        elif contract.kind == "string" and isinstance(value, str):
            sanitized[key] = _safe_text(
                value,
                fallback="unknown",
                max_length=contract.max_length,
            )
        elif contract.kind == "number" and not isinstance(value, bool) and isinstance(
            value, (int, float)
        ):
            numeric = float(value)
            if math.isfinite(numeric):
                sanitized[key] = round(numeric, 3)
        elif contract.kind == "string_list" and isinstance(value, list):
            items = [
                _safe_text(item, fallback="unknown", max_length=contract.max_length)
                for item in value[: contract.max_items]
                if isinstance(item, str)
            ]
            sanitized[key] = items
    return sanitized


def _metric_check_id(check_id: str) -> str:
    return check_id if check_id in CHECK_CATALOG else _UNKNOWN_METRIC_LABEL


def _log_probe_failure(check_id: str, diagnostic_code: str) -> None:
    safe_check_id = _metric_check_id(check_id)
    logger.warning(
        "platform readiness probe failed check_id=%s diagnostic_code=%s",
        safe_check_id,
        diagnostic_code,
        extra={
            "readiness_check_id": safe_check_id,
            "readiness_diagnostic_code": diagnostic_code,
        },
    )


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
        return ReadinessCheck(
            DEGRADED,
            "explicit public API/WS URLs are not fully configured",
            observed,
        )
    return ReadinessCheck(READY, "explicit public API/WS URLs are configured", observed)


async def check_risk_policy(app_settings: Settings) -> ReadinessCheck:
    try:
        from app.engines.risk_engine import RiskEngine

        RiskEngine()
    except Exception:
        _log_probe_failure("risk_policy", "initialization_failed")
        return ReadinessCheck(UNSAFE, "risk policy could not initialize")
    return ReadinessCheck(READY, "risk policy initialized")


async def check_database(app_settings: Settings) -> ReadinessCheck:
    async def _probe() -> None:
        from app.db.session import async_session

        async with async_session() as db:
            await db.execute(text("SELECT 1"))

    try:
        async with asyncio.timeout(app_settings.platform_readiness_dependency_timeout_seconds):
            await _probe()
    except Exception:
        _log_probe_failure("database", "dependency_unavailable")
        return ReadinessCheck(UNSAFE, "database is unavailable")
    return ReadinessCheck(READY, "database responded")


async def check_vector_schema(app_settings: Settings) -> ReadinessCheck:
    async def _probe() -> tuple[bool, str, bool, str, str, str, str, bool, bool]:
        from app.db.session import async_session

        async with async_session() as db:
            result = await db.execute(
                text(
                    """
                    SELECT
                        EXISTS (
                            SELECT 1
                            FROM pg_extension
                            WHERE extname = 'vector'
                        ) AS extension_installed,
                        COALESCE(
                            (
                                SELECT format_type(attribute.atttypid, attribute.atttypmod)
                                FROM pg_attribute AS attribute
                                WHERE attribute.attrelid = to_regclass('memory_embeddings')
                                  AND attribute.attname = 'embedding'
                                  AND NOT attribute.attisdropped
                            ),
                            'missing'
                        ) AS embedding_type,
                        to_regclass('idx_memory_embeddings_vector') IS NOT NULL AS index_exists,
                        COALESCE(
                            (
                                SELECT access_method.amname
                                FROM pg_class AS index_class
                                JOIN pg_am AS access_method ON access_method.oid = index_class.relam
                                WHERE index_class.oid = to_regclass('idx_memory_embeddings_vector')
                            ),
                            'missing'
                        ) AS index_method,
                        COALESCE(
                            (
                                SELECT operator_class.opcname
                                FROM pg_index AS index_definition
                                JOIN LATERAL unnest(index_definition.indclass) WITH ORDINALITY AS classes(opclass_oid, position)
                                  ON TRUE
                                JOIN pg_opclass AS operator_class ON operator_class.oid = classes.opclass_oid
                                WHERE index_definition.indexrelid = to_regclass('idx_memory_embeddings_vector')
                                ORDER BY classes.position
                                LIMIT 1
                            ),
                            'missing'
                        ) AS index_opclass,
                        COALESCE(
                            (
                                SELECT table_class.relname
                                FROM pg_index AS index_definition
                                JOIN pg_class AS table_class
                                  ON table_class.oid = index_definition.indrelid
                                WHERE index_definition.indexrelid = to_regclass('idx_memory_embeddings_vector')
                            ),
                            'missing'
                        ) AS index_table,
                        COALESCE(
                            (
                                SELECT attribute.attname
                                FROM pg_index AS index_definition
                                JOIN LATERAL unnest(index_definition.indkey) WITH ORDINALITY
                                  AS keys(attnum, position) ON TRUE
                                JOIN pg_attribute AS attribute
                                  ON attribute.attrelid = index_definition.indrelid
                                 AND attribute.attnum = keys.attnum
                                WHERE index_definition.indexrelid = to_regclass('idx_memory_embeddings_vector')
                                  AND keys.position = 1
                            ),
                            'missing'
                        ) AS index_column,
                        COALESCE(
                            (
                                SELECT index_definition.indisvalid
                                FROM pg_index AS index_definition
                                WHERE index_definition.indexrelid = to_regclass('idx_memory_embeddings_vector')
                            ),
                            FALSE
                        ) AS index_valid,
                        COALESCE(
                            (
                                SELECT index_definition.indisready
                                FROM pg_index AS index_definition
                                WHERE index_definition.indexrelid = to_regclass('idx_memory_embeddings_vector')
                            ),
                            FALSE
                        ) AS index_ready
                    """
                )
            )
            row = result.one()
            return (
                bool(row[0]), str(row[1]), bool(row[2]), str(row[3]), str(row[4]),
                str(row[5]), str(row[6]), bool(row[7]), bool(row[8]),
            )

    try:
        async with asyncio.timeout(app_settings.platform_readiness_dependency_timeout_seconds):
            (
                extension_installed,
                embedding_type,
                index_exists,
                index_method,
                index_opclass,
                index_table,
                index_column,
                index_valid,
                index_ready,
            ) = await _probe()
    except Exception:
        _log_probe_failure("vector_schema", "catalog_unavailable")
        status = UNSAFE if _is_production(app_settings) else DEGRADED
        return ReadinessCheck(status, "pgvector schema could not be verified")

    observed = {
        "extension_installed": extension_installed,
        "embedding_type": embedding_type,
        "index_exists": index_exists,
        "index_method": index_method,
        "index_opclass": index_opclass,
        "index_table": index_table,
        "index_column": index_column,
        "index_valid": index_valid,
        "index_ready": index_ready,
    }
    if (
        not extension_installed
        or embedding_type != "vector(1536)"
        or not index_exists
        or index_method != "hnsw"
        or index_opclass != "vector_cosine_ops"
        or index_table != "memory_embeddings"
        or index_column != "embedding"
        or not index_valid
        or not index_ready
    ):
        status = UNSAFE if _is_production(app_settings) else DEGRADED
        return ReadinessCheck(
            status,
            "pgvector extension or embedding schema does not match the required contract",
            observed,
        )
    return ReadinessCheck(READY, "pgvector embedding schema matches the required contract", observed)


async def check_redis(app_settings: Settings) -> ReadinessCheck:
    async def _probe() -> None:
        from app.storage.redis_client import get_redis

        redis = await get_redis()
        await redis.ping()

    try:
        async with asyncio.timeout(app_settings.platform_readiness_dependency_timeout_seconds):
            await _probe()
    except Exception:
        _log_probe_failure("redis", "dependency_unavailable")
        return ReadinessCheck(UNSAFE, "redis is unavailable")
    return ReadinessCheck(READY, "redis responded")


async def check_migration_heads(app_settings: Settings) -> ReadinessCheck:
    expected = _split_csv(app_settings.expected_migration_heads)
    if not expected:
        status = UNSAFE if _is_production(app_settings) else DEGRADED
        return ReadinessCheck(status, "EXPECTED_MIGRATION_HEADS is not configured")

    async def _probe() -> list[str]:
        from app.db.session import async_session

        async with async_session() as db:
            result = await db.execute(text("SELECT version_num FROM alembic_version"))
            return sorted(row[0] for row in result.fetchall())

    try:
        async with asyncio.timeout(app_settings.platform_readiness_dependency_timeout_seconds):
            observed = await _probe()
    except Exception:
        _log_probe_failure("migration_heads", "dependency_unavailable")
        return ReadinessCheck(
            UNSAFE,
            "migration DB heads could not be read",
            {"expected": expected},
        )

    if observed != expected:
        return ReadinessCheck(
            UNSAFE,
            "migration DB heads do not match EXPECTED_MIGRATION_HEADS",
            {"expected": expected, "observed": observed},
        )
    return ReadinessCheck(
        READY,
        "migration DB heads match expected heads",
        {"heads": observed},
    )


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
    return ReadinessCheck(
        READY,
        "notification provider is production-capable",
        {"provider": provider},
    )


async def check_device_identity(app_settings: Settings) -> ReadinessCheck:
    observed = {
        "device_identity_required": app_settings.device_identity_required,
        "public_ws_url_configured": bool(app_settings.public_ws_url.strip()),
    }
    if _is_production(app_settings):
        if not app_settings.device_identity_required:
            return ReadinessCheck(UNSAFE, "device identity enforcement is disabled", observed)
        if not app_settings.public_ws_url.startswith("wss://"):
            return ReadinessCheck(
                UNSAFE,
                "device WebSocket transport must use wss",
                observed,
            )
    if not app_settings.device_identity_required:
        return ReadinessCheck(DEGRADED, "device identity enforcement is disabled", observed)
    return ReadinessCheck(READY, "device identity enforcement is configured", observed)


async def check_worker_broker_and_heartbeat(app_settings: Settings) -> ReadinessCheck:
    if not app_settings.enable_celery_tasks:
        status = UNSAFE if _is_production(app_settings) else DEGRADED
        return ReadinessCheck(status, "Celery workers are disabled")

    async def _probe() -> bytes | str | None:
        import redis.asyncio as redis

        broker_url = _redis_url_with_password(
            app_settings.celery_broker_url,
            app_settings.redis_password,
        )
        broker = redis.from_url(
            broker_url,
            socket_connect_timeout=app_settings.platform_readiness_dependency_timeout_seconds,
            socket_timeout=app_settings.platform_readiness_dependency_timeout_seconds,
        )
        try:
            await broker.ping()
        finally:
            await broker.aclose()

        redis_url = _redis_url_with_password(app_settings.redis_url, app_settings.redis_password)
        redis_client = redis.from_url(
            redis_url,
            socket_connect_timeout=app_settings.platform_readiness_dependency_timeout_seconds,
            socket_timeout=app_settings.platform_readiness_dependency_timeout_seconds,
        )
        try:
            return await redis_client.get(app_settings.platform_worker_heartbeat_key)
        finally:
            await redis_client.aclose()

    try:
        async with asyncio.timeout(app_settings.platform_readiness_dependency_timeout_seconds):
            raw_value = await _probe()
    except Exception:
        _log_probe_failure("worker_heartbeat", "dependency_unavailable")
        return ReadinessCheck(UNSAFE, "worker broker is unavailable")

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
    ("vector_schema", check_vector_schema),
    ("redis", check_redis),
    ("migration_heads", check_migration_heads),
    ("notification_provider", check_notification_provider),
    ("device_identity", check_device_identity),
    ("worker_heartbeat", check_worker_broker_and_heartbeat),
)

_DETACHED_PROBE_TASKS: set[asyncio.Task[Any]] = set()
_PROBE_SLOT_LOCK = threading.Lock()
_MAX_PROBE_SLOTS = max(16, len(REQUIRED_CHECK_IDS) * 4)
_ACTIVE_PROBE_SLOTS = 0


def _definitions_are_valid(
    checks: tuple[tuple[str, CheckFunc], ...],
    *,
    allow_partial_checks: bool,
) -> bool:
    if not checks:
        return False
    names: list[str] = []
    for definition in checks:
        if not isinstance(definition, tuple) or len(definition) != 2:
            return False
        name, check = definition
        if not isinstance(name, str) or not name or not callable(check):
            return False
        if name in names:
            return False
        names.append(name)
    if allow_partial_checks:
        return True
    return len(names) == len(REQUIRED_CHECK_IDS) and set(names) == set(REQUIRED_CHECK_IDS)


def _aggregate_status(results: Mapping[str, ReadinessCheck]) -> str:
    statuses = {result.status for result in results.values()}
    if UNSAFE in statuses:
        return UNSAFE
    if DEGRADED in statuses:
        return DEGRADED
    return READY


async def _run_probe(
    check_id: str,
    check: CheckFunc,
    app_settings: Settings,
) -> ReadinessCheck:
    started_at = time.perf_counter()
    probe_task = asyncio.create_task(check(app_settings))
    try:
        result = await asyncio.shield(probe_task)
    except asyncio.CancelledError:
        current_task = asyncio.current_task()
        if current_task is not None and current_task.cancelling():
            probe_task.cancel()
            _track_detached_task(probe_task)
            raise
        _log_probe_failure(check_id, "probe_self_cancelled")
        result = ReadinessCheck(UNSAFE, "readiness check cancelled unexpectedly")
    except Exception:
        _log_probe_failure(check_id, "probe_exception")
        result = ReadinessCheck(UNSAFE, "readiness check failed")

    duration_ms = (time.perf_counter() - started_at) * 1000
    if not isinstance(result, ReadinessCheck):
        _log_probe_failure(check_id, "invalid_result")
        return ReadinessCheck(
            UNSAFE,
            "readiness check returned an invalid result",
            duration_ms=duration_ms,
        )
    if result.status not in _CANONICAL_STATUSES:
        _log_probe_failure(check_id, "invalid_status")
        return ReadinessCheck(
            UNSAFE,
            "readiness check returned an invalid status",
            duration_ms=duration_ms,
        )
    if check_id not in CHECK_CATALOG:
        _log_probe_failure(check_id, "unknown_check")
        return ReadinessCheck(
            UNSAFE,
            "readiness check is not registered",
            duration_ms=duration_ms,
        )
    return replace(result, duration_ms=duration_ms)


def _consume_detached_task(task: asyncio.Task[Any]) -> None:
    with _PROBE_SLOT_LOCK:
        _DETACHED_PROBE_TASKS.discard(task)
    if task.cancelled():
        return
    try:
        task.exception()
    except BaseException:
        return


def _track_detached_task(task: asyncio.Task[Any]) -> None:
    if task.done():
        _consume_detached_task(task)
        return
    with _PROBE_SLOT_LOCK:
        _DETACHED_PROBE_TASKS.add(task)
    task.add_done_callback(_consume_detached_task)


def _try_reserve_probe_slots(count: int) -> bool:
    global _ACTIVE_PROBE_SLOTS

    if count <= 0:
        return False
    with _PROBE_SLOT_LOCK:
        occupied = _ACTIVE_PROBE_SLOTS + len(_DETACHED_PROBE_TASKS)
        if occupied + count > _MAX_PROBE_SLOTS:
            return False
        _ACTIVE_PROBE_SLOTS += count
        return True


def _release_probe_slots(count: int) -> None:
    global _ACTIVE_PROBE_SLOTS

    with _PROBE_SLOT_LOCK:
        _ACTIVE_PROBE_SLOTS = max(0, _ACTIVE_PROBE_SLOTS - count)


async def _cancel_and_collect_probe_tasks(
    tasks: list[asyncio.Task[ReadinessCheck]],
    *,
    cleanup_grace: float,
) -> None:
    pending = {task for task in tasks if not task.done()}
    for task in pending:
        task.cancel()
    if pending:
        if cleanup_grace:
            await asyncio.wait(pending, timeout=cleanup_grace)
        else:
            await asyncio.sleep(0)
    for task in tasks:
        _track_detached_task(task)


async def _cleanup_probe_tasks_cancellation_safe(
    tasks: list[asyncio.Task[ReadinessCheck]],
    *,
    cleanup_grace: float,
) -> None:
    cleanup_task = asyncio.create_task(
        _cancel_and_collect_probe_tasks(tasks, cleanup_grace=cleanup_grace)
    )
    try:
        await asyncio.shield(cleanup_task)
    except asyncio.CancelledError:
        await cleanup_task
        raise


def _completion_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _build_payload(
    results: Mapping[str, ReadinessCheck],
    *,
    started_at: float,
) -> dict[str, Any]:
    payload = {
        "contract_version": PUBLIC_CONTRACT_VERSION,
        "scope": "platform",
        "status": _aggregate_status(results),
        "checked_at": _completion_timestamp(),
        "duration_ms": _safe_duration_ms((time.perf_counter() - started_at) * 1000),
        "checks": {name: result.as_dict(name) for name, result in results.items()},
    }
    from app.observability.metrics import record_platform_readiness

    record_platform_readiness(payload)
    return payload


async def _assess_platform_readiness_admitted(
    app_settings: Settings,
    checks: tuple[tuple[str, CheckFunc], ...],
    *,
    started_at: float,
) -> dict[str, Any]:
    tasks = [
        asyncio.create_task(
            _run_probe(check_id, check, app_settings),
            name=f"platform-readiness:{_metric_check_id(check_id)}",
        )
        for check_id, check in checks
    ]
    deadline = max(0.001, float(app_settings.platform_readiness_check_timeout_seconds))
    cleanup_grace = min(
        deadline,
        max(0.0, float(app_settings.platform_readiness_cleanup_grace_seconds)),
    )
    probe_budget = max(0.0, deadline - cleanup_grace)
    done: set[asyncio.Task[ReadinessCheck]] = set()
    timed_out: set[asyncio.Task[ReadinessCheck]] = set()
    try:
        done, pending = await asyncio.wait(tasks, timeout=probe_budget)
        timed_out = set(pending)
    finally:
        await _cleanup_probe_tasks_cancellation_safe(tasks, cleanup_grace=cleanup_grace)

    results: dict[str, ReadinessCheck] = {}
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    for (check_id, _check), task in zip(checks, tasks, strict=True):
        if task in timed_out:
            _log_probe_failure(check_id, "probe_timeout")
            results[check_id] = ReadinessCheck(
                UNSAFE,
                "readiness check timed out",
                duration_ms=elapsed_ms,
            )
        elif task.cancelled():
            _log_probe_failure(check_id, "probe_cancelled")
            results[check_id] = ReadinessCheck(
                UNSAFE,
                "readiness check cancelled unexpectedly",
                duration_ms=elapsed_ms,
            )
        elif task in done:
            results[check_id] = task.result()
        else:
            _log_probe_failure(check_id, "probe_incomplete")
            results[check_id] = ReadinessCheck(
                UNSAFE,
                "readiness check did not complete",
                duration_ms=elapsed_ms,
            )

    return _build_payload(results, started_at=started_at)


async def assess_platform_readiness(
    app_settings: Settings = settings,
    checks: tuple[tuple[str, CheckFunc], ...] = DEFAULT_CHECKS,
    *,
    allow_partial_checks: bool = False,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    if not _definitions_are_valid(checks, allow_partial_checks=allow_partial_checks):
        _log_probe_failure(_CONFIGURATION_CHECK_ID, "configuration_invalid")
        return _build_payload(
            {
                _CONFIGURATION_CHECK_ID: ReadinessCheck(
                    UNSAFE,
                    "readiness check definitions are invalid",
                )
            },
            started_at=started_at,
        )

    slot_count = len(checks)
    if not _try_reserve_probe_slots(slot_count):
        _log_probe_failure(_CONFIGURATION_CHECK_ID, "capacity_exhausted")
        return _build_payload(
            {
                _CONFIGURATION_CHECK_ID: ReadinessCheck(
                    UNSAFE,
                    "readiness probe capacity is exhausted",
                )
            },
            started_at=started_at,
        )

    try:
        return await _assess_platform_readiness_admitted(
            app_settings,
            checks,
            started_at=started_at,
        )
    finally:
        _release_probe_slots(slot_count)


_UNKNOWN_OPERATOR_ENTRY = CheckCatalogEntry(
    label="Unknown readiness check",
    owner="Platform runtime",
    next_action="Inspect readiness check registration before serving traffic.",
    runbook="platform-readiness#unknown-check",
)


def operator_readiness_payload(
    readiness: Mapping[str, Any],
    app_settings: Settings = settings,
) -> dict[str, Any]:
    raw_checks = readiness.get("checks")
    checks = raw_checks if isinstance(raw_checks, dict) else {}
    operator_checks: list[dict[str, Any]] = []
    statuses: list[str] = []

    for raw_check_id, raw_check in checks.items():
        check_id = raw_check_id if isinstance(raw_check_id, str) else _UNKNOWN_METRIC_LABEL
        check = raw_check if isinstance(raw_check, dict) else {}
        catalog_entry = CHECK_CATALOG.get(check_id)
        status = check.get("status")
        if status not in _CANONICAL_STATUSES or catalog_entry is None:
            status = UNSAFE
        statuses.append(status)
        metadata = catalog_entry or _UNKNOWN_OPERATOR_ENTRY
        row = {
            "id": check_id[:80],
            "label": metadata.label,
            "status": status,
            "summary": _safe_text(
                check.get("detail"),
                fallback="readiness state unavailable",
            ),
            "duration_ms": _safe_duration_ms(check.get("duration_ms")),
            "owner": metadata.owner,
            "next_action": metadata.next_action,
            "runbook": metadata.runbook,
        }
        observed = _sanitize_observed(check_id, check.get("observed"))
        if observed:
            row["observed"] = observed
        operator_checks.append(row)

    aggregate = readiness.get("status")
    if aggregate not in _CANONICAL_STATUSES:
        aggregate = UNSAFE
    if not operator_checks or UNSAFE in statuses:
        aggregate = UNSAFE
    elif DEGRADED in statuses and aggregate == READY:
        aggregate = DEGRADED

    return {
        "contract_version": OPERATOR_CONTRACT_VERSION,
        "scope": "platform",
        "status": aggregate,
        "checked_at": _safe_text(readiness.get("checked_at"), fallback=""),
        "stale_after_seconds": app_settings.platform_readiness_stale_after_seconds,
        "future_skew_seconds": app_settings.platform_readiness_future_skew_seconds,
        "duration_ms": _safe_duration_ms(readiness.get("duration_ms")),
        "checks": operator_checks,
    }


def readiness_http_status(readiness: Mapping[str, Any]) -> int:
    return 200 if readiness.get("status") in {READY, DEGRADED} else 503
