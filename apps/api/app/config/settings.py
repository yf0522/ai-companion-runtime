import logging

from pydantic_settings import BaseSettings

_logger = logging.getLogger(__name__)

_INSECURE_JWT_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://companion:companion_secret@postgres:5432/companion"

    # Redis
    redis_url: str = "redis://redis:6379/0"
    redis_password: str = "companion_redis_secret"  # Matches docker-compose default
    celery_broker_url: str = "redis://redis:6379/1"
    enable_celery_tasks: bool = False

    # MinIO
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin_secret"
    minio_secure: bool = False

    # JWT
    jwt_secret: str = _INSECURE_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # Model API Keys
    qwen_api_key: str = ""
    deepseek_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    google_api_key: str = ""

    # App environment
    app_env: str = "development"  # development | production
    cors_allowed_origins: str = "http://localhost:3000"  # comma-separated list
    notification_provider: str = "sandbox"  # sandbox | signed_webhook | unconfigured
    notification_outbound_url: str = ""
    notification_webhook_secret: str = ""
    notification_webhook_tolerance_seconds: int = 300
    notification_replay_ttl_seconds: int = 86400
    public_base_url: str = "http://localhost:8000"
    public_api_url: str = ""
    public_ws_url: str = ""
    require_tls: bool = False
    expected_migration_heads: str = ""
    backup_bucket: str = ""
    backup_kms_key_id: str = ""
    evidence_manifest_required: bool = False
    device_identity_required: bool = True
    controlled_elder_enrollment: bool = False
    platform_worker_heartbeat_key: str = "platform:worker:heartbeat"
    platform_worker_heartbeat_max_age_seconds: int = 120

    # OpenTelemetry
    otel_exporter_otlp_endpoint: str = "http://jaeger:4317"
    otel_service_name: str = "companion-runtime"

    # Audio HTTP endpoints (/v1/recognize, /v1/synthesize)
    max_asr_bytes: int = 2_000_000
    max_tts_chars: int = 300
    audio_endpoint_auth_required: bool = True
    asr_rate_limit_per_minute: int = 20
    tts_rate_limit_per_minute: int = 30
    rate_limit_failure_mode: str = "memory"  # memory (development only) | deny
    allow_ephemeral_sessions: bool = True  # development-only availability aid

    # Production Pi agent runtime (TypeScript sidecar — always-on; no harness fallback)
    enable_pi_runtime: bool = True
    pi_sidecar_url: str = "http://127.0.0.1:8787"
    pi_provider: str = "google"
    pi_model: str = "gemini-flash-latest"

    model_config = {"env_file": ["../../.env", ".env"], "extra": "ignore"}

    def validate_security(self):
        """Check for insecure defaults. In production, fail fast on any."""
        is_prod = self.app_env.lower() == "production"
        errors: list[str] = []

        if self.jwt_secret == _INSECURE_JWT_SECRET:
            msg = "JWT_SECRET is using the insecure default value!"
            errors.append(msg)
            _logger.critical(msg)
        elif len(self.jwt_secret) < 32:
            _logger.warning("JWT_SECRET is shorter than 32 characters — consider a stronger secret.")

        if not self.redis_password:
            msg = "REDIS_PASSWORD is not set — Redis has no authentication."
            errors.append(msg)
            _logger.warning(msg)
        elif self.redis_password == "companion_redis_secret":
            msg = "REDIS_PASSWORD is using the default value."
            errors.append(msg)
            _logger.warning(msg)

        if self.minio_secret_key == "minioadmin_secret":
            msg = "MINIO_SECRET_KEY is using the default value."
            errors.append(msg)
            _logger.warning(msg)

        if "companion_secret" in self.database_url:
            msg = "DATABASE_URL contains the default password 'companion_secret'."
            errors.append(msg)
            _logger.warning(msg)

        if self.rate_limit_failure_mode not in {"memory", "deny"}:
            errors.append("RATE_LIMIT_FAILURE_MODE must be 'memory' or 'deny'.")
        elif is_prod and self.rate_limit_failure_mode != "deny":
            errors.append("RATE_LIMIT_FAILURE_MODE must be 'deny' in production.")

        if is_prod and self.allow_ephemeral_sessions:
            errors.append("ALLOW_EPHEMERAL_SESSIONS must be false in production.")

        if is_prod:
            if not self.require_tls:
                errors.append("REQUIRE_TLS must be true in production.")
            elif not self.public_base_url.startswith("https://"):
                errors.append("PUBLIC_BASE_URL must use https when REQUIRE_TLS is true.")

            if not self.expected_migration_heads.strip():
                errors.append("EXPECTED_MIGRATION_HEADS must be set in production.")

            if not self.backup_bucket.strip():
                errors.append("BACKUP_BUCKET must be set in production.")

            if not self.backup_kms_key_id.strip():
                errors.append("BACKUP_KMS_KEY_ID must be set in production.")

            if not self.evidence_manifest_required:
                errors.append("EVIDENCE_MANIFEST_REQUIRED must be true in production.")

            if not self.public_api_url.startswith("https://"):
                errors.append("PUBLIC_API_URL must use https in production.")

            if not self.public_ws_url.startswith("wss://"):
                errors.append("PUBLIC_WS_URL must use wss in production.")

            if self.notification_provider != "signed_webhook":
                errors.append("NOTIFICATION_PROVIDER must be signed_webhook in production.")
            elif not self.notification_outbound_url.startswith("https://"):
                errors.append("NOTIFICATION_OUTBOUND_URL must use https in production.")

            if not self.notification_webhook_secret.strip():
                errors.append("NOTIFICATION_WEBHOOK_SECRET must be set in production.")

            if not self.enable_celery_tasks:
                errors.append("ENABLE_CELERY_TASKS must be true in production.")

            if not self.device_identity_required:
                errors.append("DEVICE_IDENTITY_REQUIRED must be true in production.")

            if not self.controlled_elder_enrollment:
                errors.append("CONTROLLED_ELDER_ENROLLMENT must be true in production.")

        if is_prod and errors:
            raise RuntimeError(
                "Refusing to start in production with insecure configuration:\n"
                + "\n".join(f"  - {e}" for e in errors)
                + "\nSet proper secrets in .env or change APP_ENV to 'development'."
            )


settings = Settings()
