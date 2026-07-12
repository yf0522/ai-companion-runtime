# Platform readiness runbook

This runbook is the operating contract for the platform readiness engine, the operator control center, and the local-stack doctor. Readiness is evidence about whether the current runtime can safely serve the care product; it is not a substitute for a liveness check, an incident timeline, or a full SLO dashboard.

## Endpoints and HTTP semantics

### Public `GET /ready`

`/ready` is intentionally unauthenticated so an orchestrator or local doctor can decide whether to route traffic. It returns the sanitized `platform-readiness.v1` contract with:

- `scope: "platform"`;
- aggregate `status`;
- UTC `checked_at` completion time and total `duration_ms`;
- a mapping of stable check IDs to sanitized `status`, `detail`, `duration_ms`, and allowlisted `observed` fields.

HTTP status is part of the public contract:

| Aggregate state | HTTP | Meaning |
| --- | ---: | --- |
| `ready` | 200 | All required checks are ready. |
| `degraded` | 200 | The runtime can serve in its current environment, but a named capability or production control is limited. |
| `unsafe_to_serve` | 503 | At least one required safety or dependency check failed, timed out, is invalid, or is missing. Do not route new traffic. |
| Missing or unknown state | 503 | Fail closed; treat the evidence as invalid. |

Use `/health` only for process liveness. A successful `/health` response does not establish readiness.

### Operator `GET /api/operator/platform/readiness`

This endpoint returns the enriched `operator-platform-readiness.v1` contract. Authentication is a bearer JWT accepted by the normal API auth dependency, and authorization requires the decoded claim `role` to equal the exact string `operator`. Missing or invalid authentication returns 401. Every other role, including `elder`, `family`, `admin`, or `ops`, returns 403.

A valid operator diagnostic returns HTTP 200 even when its body says `degraded` or `unsafe_to_serve`; clients must inspect the JSON `status`. The response carries `Cache-Control: no-store`. Each check is an ordered row containing `id`, `label`, `status`, `summary`, `duration_ms`, `owner`, `next_action`, `runbook`, and only allowlisted observed data.

Do not use the operator endpoint as a load-balancer probe. Use `/ready` for traffic decisions and the operator endpoint or `/ops/platform` for diagnosis.

## Interpreting evidence

The engine emits three canonical check states. The operator UI derives two additional evidence-quality states.

| State | Operator interpretation | Required response |
| --- | --- | --- |
| `ready` | Current evidence says the check is healthy. | No repair action; continue monitoring. |
| `degraded` | Service is allowed, but the named limitation is real. Common local causes include intentionally disabled workers, sandbox notifications, absent public URLs, or relaxed device identity. | Read the affected rows and record limitations. Production degradation must be assessed against the production safety contract; do not assume a local-safe limitation is production-safe. |
| `unsafe_to_serve` | A dependency, safety control, migration state, or readiness definition is unsafe or unverifiable. | Stop rollout or traffic restoration, follow the check's next action, repair, and rerun readiness. |
| stale | The operator payload has a valid timestamp older than `stale_after_seconds` (currently 60 seconds). | Treat the last result as historical evidence, not current health. Refresh before deciding. |
| unknown | The payload, timestamp, aggregate/check state, or future clock skew is invalid; transport/auth errors are also presented without a healthy summary. | Fail closed. Repair the contract, clock, authentication, or network path, then refresh. |

The current allowed future-clock tolerance is reported as `future_skew_seconds` (currently 5 seconds). Never infer zero failures or a green state when evidence is stale, unknown, forbidden, or unavailable.

## Check ownership and repair

The API's catalog is authoritative for each row's owner, next action, and runbook reference. Start with the named owner; if the row is unknown, route it to Platform runtime and keep the aggregate unsafe.

### Public API and WebSocket configuration

<a id="public-api-ws-config"></a>

- **Owner:** Platform runtime
- **Check ID:** `public_api_ws_config`
- **Repair:** Verify `PUBLIC_API_URL` and `PUBLIC_WS_URL`. Production requires explicit `https://` and `wss://` endpoints. Missing explicit URLs may be degraded in development but are unsafe in production.

### Safety risk policy

<a id="risk-policy"></a>

- **Owner:** Safety engineering
- **Check ID:** `risk_policy`
- **Repair:** Reproduce risk-engine initialization using the same environment and packaged rules. Initialization failure is unsafe; do not bypass the policy to make readiness green.

### Primary database

<a id="database"></a>

- **Owner:** Platform runtime
- **Check ID:** `database`
- **Repair:** Verify network reachability, active database credentials, capacity, and a bounded `SELECT 1`. Do not paste the database URL into tickets or chat.

### Redis

<a id="redis"></a>

- **Owner:** Platform runtime
- **Check ID:** `redis`
- **Repair:** Verify the active Redis URL, whether the selected Redis instance requires authentication, and connectivity from the API process. For the native passwordless local profile, the launcher deliberately passes an explicit empty `REDIS_PASSWORD`; preserve an explicitly supplied password for any password-protected instance. Confirm the companion memory path after repair, not only `PING`.

### Migration heads

<a id="migration-heads"></a>

- **Owner:** Release engineering
- **Check ID:** `migration_heads`
- **Repair:** Compare the database's Alembic heads with `EXPECTED_MIGRATION_HEADS`. Missing expected heads is degraded locally and unsafe in production; a mismatch is unsafe everywhere. Apply only reviewed migrations and rerun the check.

### Notification provider

<a id="notification-provider"></a>

- **Owner:** Care operations
- **Check ID:** `notification_provider`
- **Repair:** Verify the selected provider and its delivery configuration. Unconfigured or sandbox delivery may be degraded locally but is unsafe in production. Production signed webhooks require HTTPS and a configured secret; never print that secret.

### Companion device identity

<a id="device-identity"></a>

- **Owner:** Device security
- **Check ID:** `device_identity`
- **Repair:** Verify device identity enforcement and secure WebSocket transport. Disabled identity may be degraded locally; production requires identity enforcement and `wss://`.

### Worker broker and heartbeat

<a id="worker-heartbeat"></a>

- **Owner:** Platform runtime
- **Check ID:** `worker_heartbeat`
- **Repair:** Verify the broker, worker process, heartbeat key, and heartbeat age. Workers disabled may be degraded locally but are unsafe in production. Missing, malformed, stale, or unreachable heartbeat evidence is unsafe.

### Unknown check

<a id="unknown-check"></a>

- **Owner:** Platform runtime
- **Check ID:** any unregistered or invalid ID
- **Repair:** Inspect check registration and catalog drift. Unknown checks are normalized to low-cardinality `unknown` metrics and fail closed; do not add dynamic IDs to metrics or waive the failure.

## Local-stack doctor

The accepted local verification profile uses Web 3001, API 8001, and Pi sidecar 8787:

```bash
WEB_PORT=3001 API_PORT=8001 PI_SIDECAR_PORT=8787 ./scripts/local_stack.sh restart
./scripts/local_stack.sh status
./scripts/local_stack.sh doctor
```

`start` and `restart` wait for liveness and then run the same `doctor` path before announcing completion. `doctor` checks the Web login route, API liveness, Pi liveness, and the API's public `/ready` contract.

Doctor exit semantics are intentionally strict:

- exit 0 for `ready`;
- exit 0 for `degraded`, while printing the limiting check IDs;
- non-zero for `unsafe_to_serve`, unreachable processes/endpoints, malformed JSON, unknown state, or a readiness/HTTP mismatch.

The launcher persists the last successful resolved profile in `.local-stack/profile.env`, so later `status`, `stop`, and `doctor` commands reuse the same ports without repeating environment variables. Explicit environment variables override persisted values.

The profile file may contain exactly these scalar keys:

```dotenv
LOCAL_STACK_PROFILE=native
API_PORT=8001
WEB_PORT=3001
PI_SIDECAR_PORT=8787
```

It is parsed as data and never sourced or evaluated. Malformed, duplicate, missing, or unknown keys invalidate the whole persisted profile. It must never contain API keys, tokens, usernames, database/Redis URLs, passwords, or other secrets. The compatibility input alias `PI_PORT` is accepted at invocation time, but persisted state uses `PI_SIDECAR_PORT`.

## Safe diagnosis and repair sequence

1. Capture state without exposing environment values:

   ```bash
   ./scripts/local_stack.sh status
   ./scripts/local_stack.sh doctor
   curl -fsS http://127.0.0.1:8001/ready
   ```

2. If the doctor reports `unsafe_to_serve`, use the printed stable check IDs and the owner table above. Inspect `.local-stack/api.log`, `.local-stack/web.log`, or `.local-stack/pi.log`, but copy only sanitized diagnostic codes and summaries.
3. Repair the underlying dependency or configuration. Do not weaken the check, replace `/ready` with `/health`, or force the UI green.
4. Restart with the accepted ports if process environment changed, then rerun `status` and `doctor` without port overrides to prove persisted-port recovery.
5. After a Redis repair, perform one companion memory read/write and confirm the API log has no new authentication failure. Do not search for or print password values.
6. Authenticate through the normal operator login flow and inspect `http://localhost:3001/ops/platform`. Do not enable public privileged registration or fabricate a non-operator token.
7. Refresh readiness and verify that metrics increment before restoring traffic.

## Metrics and log hygiene

Prometheus metrics are exposed at `/metrics`:

- `companion_platform_readiness_evaluations_total{status}`;
- `companion_platform_readiness_checks_total{check_id,status}`;
- `companion_platform_readiness_check_duration_seconds{check_id,status}`.

Labels are deliberately low-cardinality: `status` is one of the three canonical states, and `check_id` is a stable catalog ID or `unknown`. Never add exception text, URLs, owners, household/user identifiers, timestamps, or arbitrary check IDs as labels.

Probe failures log a stable check ID and diagnostic code. Public and operator payloads sanitize credential-bearing URLs, authorization values, API keys, passwords, secrets, and tokens, but operators must still avoid copying raw environment variables or full connection strings into logs, screenshots, issues, or chat. If a credential appears in a remote surface, redact it and rotate it.

Useful non-secret evidence:

```bash
curl -fsS http://127.0.0.1:8001/metrics | rg 'companion_platform_readiness'
sed -n '1,4p' .local-stack/profile.env
```

The profile inspection is safe only after confirming it has the exact allowlisted four-key shape above.

## Verification commands

Run from the repository root unless a command changes directory:

```bash
cd apps/api
uv run pytest \
  tests/test_platform_readiness.py \
  tests/test_platform_readiness_api.py \
  tests/test_local_stack_contract.py \
  tests/test_production_failure_contracts.py \
  tests/test_product_depth_contracts.py -q
uv run ruff check \
  app/runtime/readiness.py \
  app/config/settings.py \
  app/observability/metrics.py \
  app/api/platform.py \
  app/main.py \
  tests/test_platform_readiness.py \
  tests/test_platform_readiness_api.py \
  tests/test_local_stack_contract.py
```

```bash
cd apps/web
npm test
npm run typecheck
npm run build
PLAYWRIGHT_BASE_URL=http://127.0.0.1:3001 npx playwright test e2e/operator-platform-readiness.spec.ts --project=desktop
PLAYWRIGHT_BASE_URL=http://127.0.0.1:3001 npx playwright test e2e/operator-platform-readiness.spec.ts --project=mobile
```

Repository hygiene:

```bash
git diff --check
git status --short
git diff -- . ':!*.lock' | rg -n '(GOOGLE_API_KEY|GEMINI_API_KEY|OPENAI_API_KEY|JWT_SECRET|REDIS_PASSWORD)=' || true
```

Review every hygiene match manually: a variable name or empty local value can be intentional; a credential value is not.

## Deliberately out of scope

This readiness vertical does not implement a Turn Supervisor, notification retry system, cached readiness service, external collector, full SLO dashboard, aggressive browser polling, Celery/provider enablement, Docker redesign, or new infrastructure dependency. It does not change household readiness ownership, make privileged registration public, merge or deploy code, or declare a development-only degradation safe for production. Those require separate product, security, and operational decisions.
