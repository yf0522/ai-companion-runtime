# Production Deployment

## Preconditions

- Store `.env.production.example` values in the deployment secret manager; do not commit `.env.production`.
- Terminate TLS at a reviewed ingress or load balancer and forward only trusted traffic to the private Compose network.
- Set explicit API runtime URLs: `PUBLIC_API_URL=https://...` and `PUBLIC_WS_URL=wss://...`.
- Set `EXPECTED_MIGRATION_HEADS=a9c0d1e2f3b4` and verify `alembic heads` returns that single head.
- Configure a real backup bucket and KMS key, then complete the restore drill in `backup-restore.md`.
- Configure a production-capable `NOTIFICATION_PROVIDER`; `sandbox` and `unconfigured` are never production-ready.
- Keep `DEVICE_IDENTITY_REQUIRED=true` and `ENABLE_CELERY_TASKS=true`; `/ready` requires a fresh worker heartbeat.
- Keep `CONTROLLED_ELDER_ENROLLMENT=true`; pilot elder accounts must be provisioned by operations rather than public self-registration.

## Release sequence

1. Build immutable API and web images from one commit SHA.
2. Run `alembic upgrade a9c0d1e2f3b4` as a one-off migration job.
3. Start API/workers with `infra/docker-compose.yml` plus `infra/docker-compose.production.yml`.
4. Require `/ready` to report platform `status=ready` before routing traffic. The platform readiness payload is separate from household readiness and includes risk policy, database, Redis, migration DB heads, notification provider capability, device identity enforcement, and worker broker/heartbeat checks.
5. Run role-authenticated care-task, device-auth, and production notification provider smoke checks.
6. Generate an evidence manifest with the release SHA, environment, role, migration head, and real trace/receipt identifiers.

## Rollback

- Roll application images back only when the target code supports the current schema.
- Do not downgrade a migration that has accepted production writes without a reviewed data migration.
- If safety policy, audit persistence, or distributed admission control is unavailable, remove the affected service from traffic instead of enabling a local fallback.
