from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import alerts, reminder_api
from app.api.rate_limiter import RateLimitBackendUnavailable, RateLimiter
from app.config.settings import Settings
from app.db.models import FamilyBinding
from app.engines.risk_engine import RiskConfigurationError, RiskEngine
from app.observability.trace_service import AuditPersistenceError, TraceService
from app.runtime.session_service import SessionPersistenceError, create_session
from app.runtime.risk_gate import _analyze_risk


def _production_settings(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "jwt_secret": "a-very-long-secure-jwt-secret-key-here",
        "redis_password": "strong_redis_password",
        "minio_secret_key": "strong_minio_secret",
        "database_url": "postgresql+asyncpg://user:real_pass@host/db",
        "allow_ephemeral_sessions": False,
        "rate_limit_failure_mode": "deny",
        "require_tls": True,
        "public_base_url": "https://api.example.test",
        "expected_migration_heads": "b0c1d2e3f4a5",
        "backup_bucket": "pilot-backups",
        "backup_kms_key_id": "kms-key",
        "evidence_manifest_required": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_production_rejects_memory_rate_limit_fallback():
    settings = _production_settings(rate_limit_failure_mode="memory")

    with pytest.raises(RuntimeError, match="RATE_LIMIT_FAILURE_MODE"):
        settings.validate_security()


def test_production_rejects_ephemeral_sessions():
    settings = _production_settings(allow_ephemeral_sessions=True)

    with pytest.raises(RuntimeError, match="ALLOW_EPHEMERAL_SESSIONS"):
        settings.validate_security()


def test_risk_engine_rejects_missing_rules(monkeypatch, tmp_path):
    missing = tmp_path / "missing-risk-rules.yaml"
    monkeypatch.setattr("app.engines.risk_engine._risk_rules_path", lambda: missing)

    with pytest.raises(RiskConfigurationError, match="risk rules"):
        RiskEngine()


@pytest.mark.asyncio
async def test_production_session_failure_is_not_ephemeral(monkeypatch):
    class _BrokenSessionContext:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("app.config.settings.settings.app_env", "production")
    monkeypatch.setattr("app.db.session.async_session", lambda: _BrokenSessionContext())

    with pytest.raises(SessionPersistenceError, match="persist session"):
        await create_session("elder-user")


@pytest.mark.asyncio
async def test_production_rate_limiter_fails_closed(monkeypatch):
    limiter = RateLimiter(max_requests=3, window_seconds=10, failure_mode="deny")

    async def _redis_down(_key: str) -> bool:
        raise RuntimeError("redis down")

    monkeypatch.setattr(limiter, "_check_redis", _redis_down)

    with pytest.raises(RateLimitBackendUnavailable, match="unavailable"):
        await limiter.check("test-key")


@pytest.mark.asyncio
async def test_required_audit_failure_propagates(monkeypatch):
    class _BrokenSessionContext:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("app.db.session.async_session", lambda: _BrokenSessionContext())

    with pytest.raises(AuditPersistenceError, match="critical audit"):
        await TraceService().add_event(
            trace_id="trace-critical",
            step_name="risk_decision",
            step_index=1,
            required=True,
        )


@pytest.mark.asyncio
async def test_runtime_risk_failure_blocks_instead_of_defaulting_low(monkeypatch):
    class _BrokenRiskEngine:
        async def analyze(self, _input):
            raise RuntimeError("policy unavailable")

    monkeypatch.setattr("app.engines.risk_engine.RiskEngine", _BrokenRiskEngine)

    result = await _analyze_risk(
        "elder-user",
        "session-id",
        "普通聊天",
        "trace-id",
        100,
    )

    assert result.level == "critical"
    assert result.category == "safety_unavailable"


def test_readiness_reports_dependency_failure(monkeypatch):
    class _BrokenSessionContext:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _BrokenRedis:
        async def ping(self):
            raise RuntimeError("redis down")

    async def _redis():
        return _BrokenRedis()

    monkeypatch.setattr("app.db.session.async_session", lambda: _BrokenSessionContext())
    monkeypatch.setattr("app.storage.redis_client.get_redis", _redis)

    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["scope"] == "platform"
    assert payload["status"] == "unsafe_to_serve"
    assert payload["checks"]["risk_policy"]["status"] == "ready"
    assert payload["checks"]["database"]["status"] == "unsafe_to_serve"
    assert payload["checks"]["redis"]["status"] == "unsafe_to_serve"


class _BindingResult:
    def __init__(self, binding):
        self.binding = binding

    def scalar_one_or_none(self):
        return self.binding


class _BindingSession:
    def __init__(self, binding):
        self.binding = binding

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def execute(self, _stmt):
        return _BindingResult(self.binding)


@pytest.mark.asyncio
async def test_family_binding_permissions_are_enforced_for_legacy_routes(monkeypatch):
    family_id = uuid.uuid4()
    elder_id = uuid.uuid4()
    binding = FamilyBinding(
        family_user_id=family_id,
        elder_user_id=elder_id,
        permissions=[],
    )
    monkeypatch.setattr("app.db.session.async_session", lambda: _BindingSession(binding))
    user = {"sub": str(family_id), "role": "family"}

    with pytest.raises(HTTPException) as reminder_exc:
        await reminder_api._get_managed_elder_id(user, permission="view_reminders")
    assert reminder_exc.value.status_code == 403

    with pytest.raises(HTTPException) as alert_exc:
        await alerts._get_managed_elder_id(user)
    assert alert_exc.value.status_code == 403
