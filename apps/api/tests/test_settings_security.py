"""Tests for settings security validation."""
import pytest
from app.config.settings import Settings, _INSECURE_JWT_SECRET


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
        expected_migration_heads="e1f2a3b4c5d6",
        backup_bucket="pilot-backups",
        backup_kms_key_id="kms-key",
        evidence_manifest_required=True,
    )
    with pytest.raises(RuntimeError, match="Refusing to start in production"):
        s.validate_security()


def test_production_accepts_all_real_secrets():
    s = Settings(
        app_env="production",
        jwt_secret="a-very-long-secure-jwt-secret-key-here",
        redis_password="strong_redis_password",
        minio_secret_key="strong_minio_secret",
        database_url="postgresql+asyncpg://user:real_pass@host/db",
        rate_limit_failure_mode="deny",
        allow_ephemeral_sessions=False,
        require_tls=True,
        public_base_url="https://api.example.test",
        expected_migration_heads="e1f2a3b4c5d6",
        backup_bucket="pilot-backups",
        backup_kms_key_id="kms-key",
        evidence_manifest_required=True,
    )
    # Should not raise
    s.validate_security()


def test_development_warns_but_does_not_crash():
    s = Settings(
        app_env="development",
        jwt_secret=_INSECURE_JWT_SECRET,
    )
    # Should not raise even with defaults
    s.validate_security()
