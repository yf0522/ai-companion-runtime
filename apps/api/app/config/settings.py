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

    # App environment
    app_env: str = "development"  # development | production
    cors_allowed_origins: str = "http://localhost:3000"  # comma-separated list

    # OpenTelemetry
    otel_exporter_otlp_endpoint: str = "http://jaeger:4317"
    otel_service_name: str = "companion-runtime"

    # Audio HTTP endpoints (/v1/recognize, /v1/synthesize)
    max_asr_bytes: int = 2_000_000
    max_tts_chars: int = 300
    audio_endpoint_auth_required: bool = True
    asr_rate_limit_per_minute: int = 20
    tts_rate_limit_per_minute: int = 30

    # Experimental Pi agent runtime (TypeScript sidecar — off by default)
    enable_pi_runtime: bool = False
    pi_sidecar_url: str = "http://127.0.0.1:8787"

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

        if is_prod and errors:
            raise RuntimeError(
                f"Refusing to start in production with insecure configuration:\n"
                + "\n".join(f"  - {e}" for e in errors)
                + "\nSet proper secrets in .env or change APP_ENV to 'development'."
            )


settings = Settings()
