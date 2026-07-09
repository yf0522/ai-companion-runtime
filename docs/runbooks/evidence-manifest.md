# Evidence Manifest Runbook

## Purpose

The evidence manifest records what the software can prove for a release without fabricating legal, provider, or hardware evidence.

## Generate locally

```bash
python scripts/evidence_manifest.py \
  --environment development \
  --account-role local \
  --migration-heads "$EXPECTED_MIGRATION_HEADS" \
  --trace-ids "$TRACE_IDS" \
  --receipt-ids "$RECEIPT_IDS" \
  --output docs/evidence/release-manifest.json
```

## External evidence policy

The following manifest keys default to `pending_unconfigured` unless real evidence is provided:

- `legal_review`
- `provider_delivery`
- `physical_device`
- `hardware_ota`

Do not change these values to passing states from simulator output, local screenshots, or annotated expected logs. Real provider delivery, physical-board secure boot/OTA, and legal/compliance approval are external gates.

## Required fields

- release SHA
- environment
- account role
- timestamp
- migration heads
- trace identifiers when exercising a flow
- receipt identifiers when exercising delivery
