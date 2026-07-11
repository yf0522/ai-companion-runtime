# Gate C Staging Soak (Pi-only + mem0 + FC)

Automated Gate C in CI is a **soak proxy**, not a substitute for live staging.
Live UltraQA / compose soak may be unavailable during Autopilot; treat the
checklist below as a **required residual** before production flag day.

## Preconditions

- Staging stack from `infra/docker-compose.yml` (API + `pi-sidecar` + Postgres + Redis + mem0 deps as configured).
- `ENABLE_PI_RUNTIME=true`, `DEFAULT_RUNTIME=pi`, `MEM0_ENABLED=1` (or staging equivalent).
- Non-empty `TOOL_BRIDGE_TOKEN` shared by API and `pi-sidecar`.
- Health: API `/ready` green; `pi-sidecar` healthcheck green.

## Checklist (30–60 minutes)

1. **Compose health** — `docker compose ps` shows `api` and `pi-sidecar` healthy; no restart loops.
2. **WS smoke** — Login + `ws://…/ws/chat` turn completes: `trace` → `first_reply`/`delta` → `final`; no harness / `invalid_runtime`.
3. **FC tools** — One turn each for `caretask` (list/create), `memory` (note/recall), `utility` (calculator or weather).
4. **mem0 honesty** — With granted lifecycle rows but empty mem0 search: UI/ops copy says service unavailable (not “没有已授权的长期记忆”); machine meta `no_dump=true`.
5. **Dual-path check** — Trace `memory_recall` shows `ltm_source=fc_mem0` and `vector_count=0` under `MEM0_ENABLED`; LTM content only via memory tool result.
6. **Risk fail-closed** — High/critical utterance never reaches sidecar tools; forge-low bridge request with crisis query is rejected (`risk_blocked`, `server_recheck`).
7. **Sidecar kill** — Stop `pi-sidecar` mid-session; API responds fail-closed (no harness fallback); restart restores turns.
8. **Soak window** — Keep WS churn 30–60m (or UltraQA suite); watch error rate, TTFT, sidecar restarts, mem0 timeout/no_dump metrics.

## Residual (explicit)

If staging/UltraQA cannot run in this PR cycle:

- Document acceptance of residual risk (sidecar + mem0 + FC unproven under live load).
- Schedule **Day-0 post-merge** soak using this checklist before production traffic.
- Do not flip production flags until items 1–7 pass at least once on staging.

## Related

- PR #49 Gate C cutover / Autopilot soak proxy note
- `.omx/plans/code-review-pi-only-mem0-fc.md` (M4 staging residual)
- `docs/runbooks/production-deployment.md`
