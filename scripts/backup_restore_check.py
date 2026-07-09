#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class BackupRestorePlan:
    mode: str
    environment: str
    database_url_configured: bool
    backup_bucket_configured: bool
    restore_target_configured: bool
    generated_at: str
    status: str


def build_plan(
    *,
    mode: str,
    environment: str,
    database_url: str,
    backup_bucket: str,
    restore_target_database_url: str,
) -> BackupRestorePlan:
    db_ok = bool(database_url.strip())
    bucket_ok = bool(backup_bucket.strip())
    restore_ok = bool(restore_target_database_url.strip())
    if mode == "run" and environment == "production" and not (db_ok and bucket_ok and restore_ok):
        status = "blocked_unconfigured"
    elif mode == "run" and not (db_ok and restore_ok):
        status = "blocked_unconfigured"
    else:
        status = "dry_run_ready" if mode == "dry-run" else "run_ready"
    return BackupRestorePlan(
        mode=mode,
        environment=environment,
        database_url_configured=db_ok,
        backup_bucket_configured=bucket_ok,
        restore_target_configured=restore_ok,
        generated_at=datetime.now(timezone.utc).isoformat(),
        status=status,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate backup/restore drill configuration.")
    parser.add_argument("--mode", choices=["dry-run", "run"], default="dry-run")
    parser.add_argument("--environment", default="development")
    parser.add_argument("--database-url", default="")
    parser.add_argument("--backup-bucket", default="")
    parser.add_argument("--restore-target-database-url", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    plan = build_plan(
        mode=args.mode,
        environment=args.environment,
        database_url=args.database_url,
        backup_bucket=args.backup_bucket,
        restore_target_database_url=args.restore_target_database_url,
    )
    payload = json.dumps(asdict(plan), indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 2 if plan.status == "blocked_unconfigured" else 0


if __name__ == "__main__":
    raise SystemExit(main())
