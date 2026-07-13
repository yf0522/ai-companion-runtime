"""Tests for settings security validation."""
from pathlib import Path

import pytest
from app.config.settings import Settings, _INSECURE_JWT_SECRET


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
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
        "expected_migration_heads": "c1d2e3f4a5b6",
        "backup_bucket": "pilot-backups",
        "backup_kms_key_id": "kms-key",
        "evidence_manifest_required": True,
        "notification_provider": "signed_webhook",
        "notification_outbound_url": "https://notify.example.test/events",
        "notification_webhook_secret": "provider-secret",
        "enable_celery_tasks": True,
        "device_identity_required": True,
        "controlled_elder_enrollment": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_production_rejects_default_jwt():
    s = Settings(
        app_env="production",
        jwt_secret=_INSECURE_JWT_SECRET,
        redis_password="real_password",
        minio_secret_key="real_secret",
        database_url="postgresql+asyncpg://user:real_pass@host/db",
        rate_limit_failure_mode="deny",
        allow_ephemeral_sessions=False,
    )
    with pytest.raises(RuntimeError, match="Refusing to start in production"):
        s.validate_security()


def test_production_rejects_no_redis_password():
    s = Settings(
        app_env="production",
        jwt_secret="a-very-long-secure-jwt-secret-key-here",
        redis_password="",
        minio_secret_key="real_secret",
        database_url="postgresql+asyncpg://user:real_pass@host/db",
        rate_limit_failure_mode="deny",
        allow_ephemeral_sessions=False,
    )
    with pytest.raises(RuntimeError, match="Refusing to start in production"):
        s.validate_security()


def test_production_rejects_default_redis_password():
    s = Settings(
        app_env="production",
        jwt_secret="a-very-long-secure-jwt-secret-key-here",
        redis_password="companion_redis_secret",
        minio_secret_key="real_secret",
        database_url="postgresql+asyncpg://user:real_pass@host/db",
        rate_limit_failure_mode="deny",
        allow_ephemeral_sessions=False,
        require_tls=True,
        public_base_url="https://api.example.test",
        public_api_url="https://api.example.test",
        public_ws_url="wss://api.example.test",
        expected_migration_heads="c1d2e3f4a5b6",
        backup_bucket="pilot-backups",
        backup_kms_key_id="kms-key",
        evidence_manifest_required=True,
        notification_provider="signed_webhook",
        notification_outbound_url="https://notify.example.test/events",
        notification_webhook_secret="provider-secret",
        enable_celery_tasks=True,
        device_identity_required=True,
        controlled_elder_enrollment=True,
    )
    with pytest.raises(RuntimeError, match="Refusing to start in production"):
        s.validate_security()


def test_production_accepts_all_real_secrets():
    s = _production_settings(public_base_url="https://8.8.8.8")
    # Should not raise
    s.validate_security()


@pytest.mark.parametrize(
    ("field", "url"),
    [
        ("public_base_url", "https://localhost"),
        ("public_api_url", "https://127.0.0.1/api"),
        ("public_api_url", "https://0.0.0.0/api"),
        ("public_api_url", "https://10.0.0.1/api"),
        ("public_ws_url", "wss://[::1]/ws"),
        ("notification_outbound_url", "https://169.254.1.2/events"),
        ("notification_outbound_url", "https://localhost/events"),
    ],
)
def test_production_rejects_non_public_endpoint_hosts(field, url):
    with pytest.raises(RuntimeError, match="publicly routable host"):
        _production_settings(**{field: url}).validate_security()


def test_production_rejects_stale_expected_migration_head():
    s = _production_settings(expected_migration_heads="b0c1d2e3f4a5")

    with pytest.raises(RuntimeError, match="current sole head c1d2e3f4a5b6"):
        s.validate_security()


def test_production_example_uses_current_sole_migration_head():
    root = Path(__file__).resolve().parents[3]
    example = (root / ".env.production.example").read_text(encoding="utf-8")
    assert "EXPECTED_MIGRATION_HEADS=c1d2e3f4a5b6" in example
    assert "EXPECTED_MIGRATION_HEADS=a9c0d1e2f3b4" not in example


def test_development_warns_but_does_not_crash():
    s = Settings(
        app_env="development",
        jwt_secret=_INSECURE_JWT_SECRET,
    )
    # Should not raise even with defaults
    s.validate_security()
