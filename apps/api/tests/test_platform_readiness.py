from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime

import pytest

from app.config.settings import Settings
from app.observability.metrics import (
    PLATFORM_READINESS_CHECKS_TOTAL,
    PLATFORM_READINESS_EVALUATIONS_TOTAL,
)
from app.runtime.readiness import (
    DEGRADED,
    READY,
    UNSAFE,
    ReadinessCheck,
    assess_platform_readiness,
    check_redis,
    check_device_identity,
    check_database,
    check_migration_heads,
    check_notification_provider,
    check_public_api_ws_config,
    check_worker_broker_and_heartbeat,
    operator_readiness_payload,
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
        "expected_migration_heads": "b0c1d2e3f4a5",
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
        checks=(("redis", _ready_check), ("database", _ready_check)),
        allow_partial_checks=True,
    )

    assert payload["contract_version"] == "platform-readiness.v1"
    assert payload["scope"] == "platform"
    assert payload["status"] == READY
    assert readiness_http_status(payload) == 200
    assert payload["checks"]["redis"]["status"] == READY
    assert payload["duration_ms"] >= 0
    assert payload["checks"]["redis"]["duration_ms"] >= 0
    assert datetime.fromisoformat(payload["checked_at"].replace("Z", "+00:00")).tzinfo


async def test_platform_readiness_reports_degraded_without_failing_http():
    payload = await assess_platform_readiness(
        _production_settings(),
        checks=(("redis", _ready_check), ("database", _degraded_check)),
        allow_partial_checks=True,
    )

    assert payload["status"] == DEGRADED
    assert readiness_http_status(payload) == 200


async def test_platform_readiness_reports_unsafe_and_503_on_failed_check():
    payload = await assess_platform_readiness(
        _production_settings(),
        checks=(("redis", _ready_check), ("database", _unsafe_check)),
        allow_partial_checks=True,
    )

    assert payload["status"] == UNSAFE
    assert readiness_http_status(payload) == 503
    assert payload["checks"]["database"]["detail"] == "unsafe"


async def test_platform_readiness_starts_checks_together_and_preserves_declared_order():
    started: list[str] = []
    both_started = asyncio.Event()

    def _probe(name: str):
        async def _check(_settings):
            started.append(name)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=0.2)
            return ReadinessCheck(READY, f"{name} ready")

        return _check

    payload = await assess_platform_readiness(
        _production_settings(platform_readiness_check_timeout_seconds=0.3),
        checks=(("redis", _probe("redis")), ("database", _probe("database"))),
        allow_partial_checks=True,
    )

    assert started == ["redis", "database"]
    assert list(payload["checks"]) == ["redis", "database"]
    assert payload["status"] == READY


async def test_platform_readiness_hard_deadline_does_not_wait_for_resistant_cancellation():
    cancellation_seen = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def _resistant(_settings):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_seen.set()
            await release.wait()
        finally:
            finished.set()
        return ReadinessCheck(READY, "late result")

    started_at = time.perf_counter()
    try:
        payload = await assess_platform_readiness(
            _production_settings(
                platform_readiness_check_timeout_seconds=0.03,
                platform_readiness_cleanup_grace_seconds=0.01,
            ),
            checks=(("redis", _ready_check), ("database", _resistant)),
            allow_partial_checks=True,
        )

        assert time.perf_counter() - started_at < 0.2
        assert cancellation_seen.is_set()
        assert payload["status"] == UNSAFE
        assert payload["checks"]["redis"]["status"] == READY
        assert payload["checks"]["database"]["status"] == UNSAFE
        assert payload["checks"]["database"]["detail"] == "readiness check timed out"
        assert [
            task
            for task in asyncio.all_tasks()
            if not task.done() and task.get_name().startswith("platform-readiness:")
        ] == []
    finally:
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=0.2)
        await asyncio.sleep(0)


async def test_caller_cancellation_cleans_probe_tasks_before_propagating():
    probe_started = asyncio.Event()
    probe_cancelled = asyncio.Event()

    async def _slow_probe(_settings):
        probe_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            probe_cancelled.set()

    assessment = asyncio.create_task(
        assess_platform_readiness(
            _production_settings(platform_readiness_cleanup_grace_seconds=0.05),
            checks=(("redis", _slow_probe),),
            allow_partial_checks=True,
        )
    )
    await asyncio.wait_for(probe_started.wait(), timeout=0.2)

    assessment.cancel()
    with pytest.raises(asyncio.CancelledError):
        await assessment

    await asyncio.wait_for(probe_cancelled.wait(), timeout=0.2)
    await asyncio.sleep(0)
    live_probe_tasks = [
        task
        for task in asyncio.all_tasks()
        if not task.done() and task.get_name().startswith("platform-readiness:")
    ]
    assert live_probe_tasks == []


async def test_probe_self_cancellation_is_fail_closed_instead_of_escaping():
    async def _self_cancel(_settings):
        raise asyncio.CancelledError("Bearer self-cancel-secret")

    payload = await assess_platform_readiness(
        _production_settings(),
        checks=(("redis", _self_cancel),),
        allow_partial_checks=True,
    )

    assert payload["status"] == UNSAFE
    assert payload["checks"]["redis"]["status"] == UNSAFE
    assert payload["checks"]["redis"]["detail"] == (
        "readiness check cancelled unexpectedly"
    )
    assert "self-cancel-secret" not in json.dumps(payload)


async def test_database_readiness_applies_the_dependency_timeout(monkeypatch):
    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, _statement):
            await asyncio.Event().wait()

    monkeypatch.setattr("app.db.session.async_session", lambda: _Session())
    started_at = time.perf_counter()

    check = await check_database(
        _production_settings(platform_readiness_dependency_timeout_seconds=0.01)
    )

    assert time.perf_counter() - started_at < 0.2
    assert check.status == UNSAFE
    assert check.detail == "database is unavailable"


async def test_platform_readiness_sanitizes_exceptions_from_payload_and_logs(caplog):
    secret = "postgresql://user:super-secret@db.example.test/runtime"

    async def _raises(_settings):
        raise RuntimeError(secret)

    with caplog.at_level(logging.WARNING, logger="app.runtime.readiness"):
        payload = await assess_platform_readiness(
            _production_settings(),
            checks=(("database", _raises),),
            allow_partial_checks=True,
        )

    serialized = json.dumps(payload)
    assert payload["checks"]["database"]["detail"] == "readiness check failed"
    assert secret not in serialized
    assert secret not in caplog.text
    assert "probe_exception" in caplog.text


async def test_platform_readiness_redacts_secret_bearing_detail_text():
    async def _leaky_result(_settings):
        return ReadinessCheck(
            UNSAFE,
            "redis://:top-secret@redis.example.test/0 token=abc123",
        )

    payload = await assess_platform_readiness(
        _production_settings(),
        checks=(("redis", _leaky_result),),
        allow_partial_checks=True,
    )

    detail = payload["checks"]["redis"]["detail"]
    assert "top-secret" not in detail
    assert "abc123" not in detail
    assert "[redacted]" in detail


@pytest.mark.parametrize(
    ("detail", "secret"),
    [
        ("Authorization: Bearer bearer-secret", "bearer-secret"),
        ("authorization=Basic YmFzaWMtc2VjcmV0", "YmFzaWMtc2VjcmV0"),
        ("Proxy-Authorization: Basic proxy-secret", "proxy-secret"),
        ("X-API-Key: header-key-secret", "header-key-secret"),
        ("X-Goog-Api-Key: google-header-secret", "google-header-secret"),
        ("ApiKey standalone-api-secret", "standalone-api-secret"),
        ("Bearer standalone-bearer-secret", "standalone-bearer-secret"),
    ],
)
async def test_public_and_operator_serializers_redact_authorization_variants(detail, secret):
    async def _leaky_result(_settings):
        return ReadinessCheck(UNSAFE, detail)

    public_payload = await assess_platform_readiness(
        _production_settings(),
        checks=(("redis", _leaky_result),),
        allow_partial_checks=True,
    )
    operator_payload = operator_readiness_payload(public_payload, _production_settings())

    assert secret not in json.dumps(public_payload)
    assert secret not in json.dumps(operator_payload)
    assert "[redacted]" in public_payload["checks"]["redis"]["detail"]


async def test_redis_readiness_uses_native_timeouts_without_logging_connection_secrets(
    monkeypatch,
    caplog,
):
    from app.storage import redis_client

    secret = "redis-password-secret"
    captured: dict[str, object] = {}

    class _Redis:
        async def ping(self):
            return True

    def _from_url(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Redis()

    monkeypatch.setattr(redis_client, "_pool", None)
    monkeypatch.setattr(redis_client.redis, "from_url", _from_url)
    monkeypatch.setattr(
        redis_client.settings,
        "redis_url",
        f"redis://:{secret}@redis.example.test:6379/0",
    )
    monkeypatch.setattr(redis_client.settings, "redis_password", secret)
    monkeypatch.setattr(
        redis_client.settings,
        "platform_readiness_dependency_timeout_seconds",
        0.17,
    )

    with caplog.at_level(logging.INFO, logger="app.storage.redis_client"):
        payload = await assess_platform_readiness(
            _production_settings(platform_readiness_dependency_timeout_seconds=0.17),
            checks=(("redis", check_redis),),
            allow_partial_checks=True,
        )

    assert payload["status"] == READY
    assert secret not in json.dumps(payload)
    assert secret not in caplog.text
    assert "Redis client initialized" in caplog.text
    assert "socket_connect_timeout" not in captured
    assert "socket_timeout" not in captured


async def test_platform_readiness_total_budget_includes_cleanup_grace():
    release = asyncio.Event()

    async def _resistant(_settings):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()
        return ReadinessCheck(READY, "late result")

    started_at = time.perf_counter()
    try:
        payload = await assess_platform_readiness(
            _production_settings(
                platform_readiness_check_timeout_seconds=0.06,
                platform_readiness_cleanup_grace_seconds=0.04,
            ),
            checks=(("redis", _resistant),),
            allow_partial_checks=True,
        )
        elapsed = time.perf_counter() - started_at
        assert elapsed < 0.09
        assert payload["status"] == UNSAFE
        assert payload["checks"]["redis"]["detail"] == "readiness check timed out"
    finally:
        release.set()
        await asyncio.sleep(0)


async def test_platform_readiness_normalizes_invalid_status_to_unsafe():
    async def _invalid(_settings):
        return ReadinessCheck("mystery", "should not survive")

    payload = await assess_platform_readiness(
        _production_settings(),
        checks=(("redis", _invalid),),
        allow_partial_checks=True,
    )

    assert payload["status"] == UNSAFE
    assert payload["checks"]["redis"]["status"] == UNSAFE
    assert payload["checks"]["redis"]["detail"] == "readiness check returned an invalid status"


@pytest.mark.parametrize(
    "checks",
    [
        (),
        (("redis", _ready_check), ("redis", _ready_check)),
        (("redis", _ready_check),),
        (("not_registered", _ready_check),),
    ],
)
async def test_platform_readiness_definitions_fail_closed_without_partial_test_seam(checks):
    payload = await assess_platform_readiness(_production_settings(), checks=checks)

    assert payload["status"] == UNSAFE
    assert payload["checks"]["readiness_configuration"]["status"] == UNSAFE
    assert payload["checks"]["readiness_configuration"]["detail"] == (
        "readiness check definitions are invalid"
    )


async def test_platform_readiness_filters_observed_fields_by_catalog_contract():
    async def _provider(_settings):
        return ReadinessCheck(
            DEGRADED,
            "provider limited",
            {
                "provider": "x" * 500,
                "error": "secret-token",
                "public_api_url_configured": "not-a-bool",
            },
        )

    async def _unknown(_settings):
        return ReadinessCheck(READY, "pretends ready", {"provider": "secret-provider"})

    payload = await assess_platform_readiness(
        _production_settings(),
        checks=(("notification_provider", _provider), ("custom_probe", _unknown)),
        allow_partial_checks=True,
    )

    provider_observed = payload["checks"]["notification_provider"]["observed"]
    assert provider_observed == {"provider": "x" * 80}
    assert "observed" not in payload["checks"]["custom_probe"]
    assert payload["checks"]["custom_probe"]["status"] == UNSAFE


async def test_migration_head_lists_are_copied_and_bounded_for_operator_evidence():
    heads = [f"revision-{index}-{'x' * 100}" for index in range(25)]

    async def _migration_heads(_settings):
        return ReadinessCheck(READY, "migration heads match", {"heads": heads})

    readiness = await assess_platform_readiness(
        _production_settings(),
        checks=(("migration_heads", _migration_heads),),
        allow_partial_checks=True,
    )
    payload = operator_readiness_payload(readiness, _production_settings())
    heads[0] = "mutated-after-assessment"

    observed = payload["checks"][0]["observed"]["heads"]
    assert len(observed) == 20
    assert all(len(item) <= 80 for item in observed)
    assert "mutated-after-assessment" not in observed


async def test_operator_payload_enriches_catalog_and_fails_unknown_check_closed():
    readiness = await assess_platform_readiness(
        _production_settings(),
        checks=(("redis", _ready_check), ("custom_probe", _ready_check)),
        allow_partial_checks=True,
    )

    payload = operator_readiness_payload(readiness, _production_settings())

    assert payload["contract_version"] == "operator-platform-readiness.v1"
    assert payload["stale_after_seconds"] == 60
    assert [item["id"] for item in payload["checks"]] == ["redis", "custom_probe"]
    assert payload["checks"][0]["owner"] == "Platform runtime"
    assert payload["checks"][0]["runbook"] == "platform-readiness#redis"
    assert payload["checks"][1]["status"] == UNSAFE
    assert payload["checks"][1]["label"] == "Unknown readiness check"


def test_operator_payload_fails_closed_when_diagnostic_checks_are_missing():
    payload = operator_readiness_payload(
        {
            "scope": "platform",
            "status": READY,
            "checked_at": "2026-07-12T08:30:00Z",
            "duration_ms": 1.0,
            "checks": {},
        },
        _production_settings(),
    )

    assert payload["status"] == UNSAFE
    assert payload["checks"] == []


async def test_platform_readiness_metrics_increment_with_bounded_labels():
    aggregate_before = PLATFORM_READINESS_EVALUATIONS_TOTAL.labels(status=UNSAFE)._value.get()
    known_before = PLATFORM_READINESS_CHECKS_TOTAL.labels(
        check_id="redis", status=READY
    )._value.get()
    unknown_before = PLATFORM_READINESS_CHECKS_TOTAL.labels(
        check_id="unknown", status=UNSAFE
    )._value.get()

    await assess_platform_readiness(
        _production_settings(),
        checks=(("redis", _ready_check), ("hostile-user-value", _ready_check)),
        allow_partial_checks=True,
    )

    assert PLATFORM_READINESS_EVALUATIONS_TOTAL.labels(status=UNSAFE)._value.get() == (
        aggregate_before + 1
    )
    assert PLATFORM_READINESS_CHECKS_TOTAL.labels(check_id="redis", status=READY)._value.get() == (
        known_before + 1
    )
    assert PLATFORM_READINESS_CHECKS_TOTAL.labels(
        check_id="unknown", status=UNSAFE
    )._value.get() == (unknown_before + 1)


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
