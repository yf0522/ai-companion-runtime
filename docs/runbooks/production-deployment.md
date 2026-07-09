# Production Deployment

## Preconditions

- Store `.env.production.example` values in the deployment secret manager; do not commit `.env.production`.
- Terminate TLS at a reviewed ingress or load balancer and forward only trusted traffic to the private Compose network.
- Set `EXPECTED_MIGRATION_HEADS=e1f2a3b4c5d6` and verify `alembic heads` returns that single head.
- Configure a real backup bucket and KMS key, then complete the restore drill in `backup-restore.md`.
- Keep `NOTIFICATION_PROVIDER=unconfigured` until a reviewed provider credential and callback verification are installed.

## Release sequence

1. Build immutable API and web images from one commit SHA.
2. Run `alembic upgrade e1f2a3b4c5d6` as a one-off migration job.
3. Start API/workers with `infra/docker-compose.yml` plus `infra/docker-compose.production.yml`.
4. Require `/ready` to report risk policy, database, and Redis as `ok` before routing traffic.
5. Run role-authenticated care-task, device-auth, and notification-unconfigured smoke checks.
6. Generate an evidence manifest with the release SHA, environment, role, migration head, and real trace/receipt identifiers.

## Rollback

- Roll application images back only when the target code supports the current schema.
- Do not downgrade a migration that has accepted production writes without a reviewed data migration.
- If safety policy, audit persistence, or distributed admission control is unavailable, remove the affected service from traffic instead of enabling a local fallback.
