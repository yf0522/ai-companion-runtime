# Backup and Restore Runbook

## Scope

This runbook verifies that a pilot operator can produce a backup/restore drill record without claiming that production backups are configured before secrets, buckets, and restore targets exist.

## Local dry run

```bash
python scripts/backup_restore_check.py \
  --mode dry-run \
  --environment development \
  --database-url "$DATABASE_URL" \
  --output docs/evidence/backup-restore-dry-run.json
```

Expected status: `dry_run_ready`.

## Production run gate

Production mode must provide:

- `DATABASE_URL`
- `BACKUP_BUCKET`
- `BACKUP_KMS_KEY_ID`
- restore target database URL isolated from production

Run mode blocks with `blocked_unconfigured` when these are absent:

```bash
python scripts/backup_restore_check.py \
  --mode run \
  --environment production \
  --database-url "$DATABASE_URL" \
  --backup-bucket "$BACKUP_BUCKET" \
  --restore-target-database-url "$RESTORE_TARGET_DATABASE_URL"
```

## Evidence to retain

- release SHA
- migration heads
- source database identifier
- restore target identifier
- drill timestamp
- row-count and checksum summary
- operator account role

External storage-provider proof remains pending until configured in the pilot account.
