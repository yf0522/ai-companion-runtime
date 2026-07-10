from __future__ import annotations

from app.config.settings import Settings
from app.runtime.readiness import (
    DEGRADED,
    READY,
    UNSAFE,
    ReadinessCheck,
    assess_platform_readiness,
    check_device_identity,
    check_migration_heads,
    check_notification_provider,
    check_public_api_ws_config,
    check_worker_broker_and_heartbeat,
    readiness_http_status,
)


def _production_settings(**overrides):
    values = {
        "app_env": "production",
        "jwt_secret": "a-very-long-secure-jwt-secret-key-here",
        "redis_password": "strong_redis_password",
        "minio_secret_key": "strong_minio_secret",
        "database_url": "postgresql+asyncpg://user:real_pass@host/db",
        "rate_limit_failure_mode": "deny",
        "allow_ephemeral_sessions": False,
        "require_tls": True,
        "public_base_url": "https://api.example.test",
        "public_api_url": "https://api.example.test",
        "public_ws_url": "wss://api.example.test",
        "expected_migration_heads": "f2a3b4c5d6e7",
        "backup_bucket": "pilot-backups",
        "backup_kms_key_id": "kms-key",
        "evidence_manifest_required": True,
        "notification_provider": "signed_webhook",
        "notification_outbound_url": "https://notify.example.test/outbound",
        "notification_webhook_secret": "webhook-secret",
        "enable_celery_tasks": True,
    }
    values.update(overrides)
    return Settings(**values)


async def _ready_check(settings):
    return ReadinessCheck(READY, "ok")


async def _degraded_check(settings):
    return ReadinessCheck(DEGRADED, "degraded")


async def _unsafe_check(settings):
    return ReadinessCheck(UNSAFE, "unsafe")


async def test_platform_readiness_reports_ready_when_all_checks_ready():
    payload = await assess_platform_readiness(
        _production_settings(),
        checks=(("one", _ready_check), ("two", _ready_check)),
    )

    assert payload["scope"] == "platform"
    assert payload["status"] == READY
    assert readiness_http_status(payload) == 200
    assert payload["checks"]["one"]["status"] == READY


async def test_platform_readiness_reports_degraded_without_failing_http():
    payload = await assess_platform_readiness(
        _production_settings(),
        checks=(("one", _ready_check), ("two", _degraded_check)),
    )

    assert payload["status"] == DEGRADED
    assert readiness_http_status(payload) == 200


async def test_platform_readiness_reports_unsafe_and_503_on_failed_check():
    payload = await assess_platform_readiness(
        _production_settings(),
        checks=(("one", _ready_check), ("two", _unsafe_check)),
    )

    assert payload["status"] == UNSAFE
    assert readiness_http_status(payload) == 503
    assert payload["checks"]["two"]["detail"] == "unsafe"


async def test_production_public_api_ws_config_requires_explicit_tls_urls():
    check = await check_public_api_ws_config(
        _production_settings(public_api_url="http://api.example.test", public_ws_url="")
    )

    assert check.status == UNSAFE
    assert "PUBLIC_API_URL must use https" in check.detail
    assert "PUBLIC_WS_URL is not set" in check.detail


async def test_production_notification_provider_rejects_sandbox():
    check = await check_notification_provider(_production_settings(notification_provider="sandbox"))

    assert check.status == UNSAFE
    assert check.observed["provider"] == "sandbox"


async def test_production_signed_webhook_requires_capability_config():
    check = await check_notification_provider(
        _production_settings(notification_outbound_url="", notification_webhook_secret="")
    )

    assert check.status == UNSAFE
    assert "NOTIFICATION_OUTBOUND_URL must use https" in check.detail
    assert "NOTIFICATION_WEBHOOK_SECRET is not set" in check.detail


async def test_production_device_identity_must_be_enforced():
    check = await check_device_identity(_production_settings(device_identity_required=False))

    assert check.status == UNSAFE
    assert check.observed["device_identity_required"] is False


async def test_production_migration_heads_requires_expected_heads():
    check = await check_migration_heads(_production_settings(expected_migration_heads=""))

    assert check.status == UNSAFE
    assert check.detail == "EXPECTED_MIGRATION_HEADS is not configured"


async def test_production_worker_readiness_requires_enabled_workers():
    check = await check_worker_broker_and_heartbeat(_production_settings(enable_celery_tasks=False))

    assert check.status == UNSAFE
    assert check.detail == "Celery workers are disabled"
