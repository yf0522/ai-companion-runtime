# Production Deployment

## Preconditions

- Store `.env.production.example` values in the deployment secret manager; do not commit `.env.production`.
- Terminate TLS at a reviewed ingress or load balancer and forward only trusted traffic to the private Compose network.
- Set explicit API runtime URLs: `PUBLIC_API_URL=https://...` and `PUBLIC_WS_URL=wss://...`.
- Set `EXPECTED_MIGRATION_HEADS=c1d2e3f4a5b6` and verify `alembic heads` returns that single head.
- Ensure the migration role can enable the `vector` extension. The head migration fails closed unless `memory_embeddings.embedding` is already `vector(1536)`; an incompatible column requires a reviewed, rehearsed maintenance migration rather than an unbounded deployment-time rewrite. A missing or incorrect HNSW cosine index is replaced with `CREATE INDEX CONCURRENTLY` outside the migration transaction. The c1 downgrade is intentionally a no-op to preserve forward-schema compatibility and production data.
- Configure a real backup bucket and KMS key, then complete the restore drill in `backup-restore.md`.
- Configure a production-capable `NOTIFICATION_PROVIDER`; `sandbox` and `unconfigured` are never production-ready.
- Keep `DEVICE_IDENTITY_REQUIRED=true` and `ENABLE_CELERY_TASKS=true`; `/ready` requires a fresh worker heartbeat.
- Keep `CONTROLLED_ELDER_ENROLLMENT=true`; pilot elder accounts must be provisioned by operations rather than public self-registration.

## Release sequence

From the repository root, resolve the production model and build the Web image with the same explicit public values:

```bash
docker compose --env-file .env.production \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.production.yml \
  config --format json > /tmp/companion-production-compose.json
docker compose --env-file .env.production \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.production.yml \
  build web
```

The explicit `--env-file` supplies Compose interpolation for the required Web build arguments and same-value environment contract. A service-level `env_file` only injects values into the container; it does not supply Compose interpolation. `NEXT_PUBLIC_*` values are build-time inlined into the browser bundle: changing runner environment variables cannot reconfigure an already-built client. Reject localhost, loopback, non-HTTPS API, and non-WSS WebSocket values, and rebuild the Web image whenever these values change. The production overlay clears every inherited published port; reviewed ingress joins the private network instead of publishing Compose service ports.

1. Build immutable API and web images from one commit SHA.
2. Run `alembic upgrade c1d2e3f4a5b6` as a one-off migration job.
3. Start API/workers with `infra/docker-compose.yml` plus `infra/docker-compose.production.yml`.
4. Require `/ready` to report platform `status=ready` before routing traffic. The platform readiness payload is separate from household readiness and includes risk policy, database, pgvector schema integrity, Redis, migration DB heads, notification provider capability, device identity enforcement, and worker broker/heartbeat checks.
5. Run role-authenticated care-task, device-auth, and production notification provider smoke checks.
6. Generate an evidence manifest with the release SHA, environment, role, migration head, and real trace/receipt identifiers.

## Rollback

- Roll application images back only when the target code supports the current schema.
- Do not downgrade a migration that has accepted production writes without a reviewed data migration.
- If safety policy, audit persistence, or distributed admission control is unavailable, remove the affected service from traffic instead of enabling a local fallback.
