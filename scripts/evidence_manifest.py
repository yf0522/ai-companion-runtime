#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


EXTERNAL_EVIDENCE_KEYS = (
    "legal_review",
    "provider_delivery",
    "physical_device",
    "hardware_ota",
)


@dataclass(frozen=True)
class EvidenceManifest:
    release_sha: str
    environment: str
    account_role: str
    generated_at: str
    migration_heads: list[str]
    trace_ids: list[str] = field(default_factory=list)
    receipt_ids: list[str] = field(default_factory=list)
    external_evidence: dict[str, str] = field(default_factory=dict)


def current_git_sha(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def build_manifest(
    *,
    repo_root: Path,
    environment: str,
    account_role: str,
    migration_heads: list[str],
    trace_ids: list[str],
    receipt_ids: list[str],
    external_evidence: dict[str, str] | None = None,
) -> EvidenceManifest:
    provided = external_evidence or {}
    external = {key: provided.get(key, "pending_unconfigured") for key in EXTERNAL_EVIDENCE_KEYS}
    return EvidenceManifest(
        release_sha=current_git_sha(repo_root),
        environment=environment,
        account_role=account_role,
        generated_at=datetime.now(timezone.utc).isoformat(),
        migration_heads=sorted(head for head in migration_heads if head),
        trace_ids=trace_ids,
        receipt_ids=receipt_ids,
        external_evidence=external,
    )


def parse_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Generate production evidence manifest JSON.")
    parser.add_argument("--environment", default=os.getenv("APP_ENV", "development"))
    parser.add_argument("--account-role", default=os.getenv("ACCOUNT_ROLE", "local"))
    parser.add_argument("--migration-heads", default=os.getenv("EXPECTED_MIGRATION_HEADS", ""))
    parser.add_argument("--trace-ids", default="")
    parser.add_argument("--receipt-ids", default="")
    parser.add_argument("--output", type=Path)
    for key in EXTERNAL_EVIDENCE_KEYS:
        parser.add_argument(f"--{key.replace('_', '-')}", default="")
    args = parser.parse_args()

    external = {
        key: getattr(args, key)
        for key in EXTERNAL_EVIDENCE_KEYS
        if getattr(args, key)
    }
    manifest = build_manifest(
        repo_root=repo_root,
        environment=args.environment,
        account_role=args.account_role,
        migration_heads=parse_csv(args.migration_heads),
        trace_ids=parse_csv(args.trace_ids),
        receipt_ids=parse_csv(args.receipt_ids),
        external_evidence=external,
    )
    payload = json.dumps(asdict(manifest), indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
