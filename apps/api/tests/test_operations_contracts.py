from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from app.config.settings import Settings

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, _REPO_ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_backup_restore = _load_script_module("backup_restore_check", "scripts/backup_restore_check.py")
_evidence_manifest = _load_script_module("evidence_manifest", "scripts/evidence_manifest.py")


def test_production_config_requires_tls_migrations_backup_and_evidence():
    settings = Settings(
        app_env="production",
        jwt_secret="a-very-long-secure-jwt-secret-key-here",
        redis_password="strong_redis_password",
        minio_secret_key="strong_minio_secret",
        database_url="postgresql+asyncpg://user:real_pass@host/db",
        rate_limit_failure_mode="deny",
        allow_ephemeral_sessions=False,
        require_tls=True,
        public_base_url="https://api.example.test",
        public_api_url="https://api.example.test",
        public_ws_url="wss://api.example.test",
        expected_migration_heads="f2a3b4c5d6e7",
        backup_bucket="pilot-backups",
        backup_kms_key_id="kms-key",
        evidence_manifest_required=True,
        notification_provider="signed_webhook",
        notification_outbound_url="https://notify.example.test/events",
        notification_webhook_secret="provider-secret",
        enable_celery_tasks=True,
        device_identity_required=True,
        controlled_elder_enrollment=True,
        enable_pi_runtime=True,
        tool_bridge_token="bridge-secret-at-least-16chars",
    )
    settings.validate_security()


def test_evidence_manifest_keeps_external_evidence_pending_by_default():
    manifest = _evidence_manifest.build_manifest(
        repo_root=_REPO_ROOT,
        environment="ci",
        account_role="ci",
        migration_heads=["f2a3b4c5d6e7"],
        trace_ids=["trace-1"],
        receipt_ids=["receipt-1"],
    )
    assert manifest.migration_heads == ["f2a3b4c5d6e7"]
    assert manifest.external_evidence["legal_review"] == "pending_unconfigured"
    assert manifest.external_evidence["physical_device"] == "pending_unconfigured"


def test_backup_restore_run_blocks_when_production_targets_unconfigured():
    plan = _backup_restore.build_plan(
        mode="run",
        environment="production",
        database_url="postgresql://prod/companion",
        backup_bucket="",
        restore_target_database_url="",
    )
    assert plan.status == "blocked_unconfigured"
