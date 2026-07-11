# Memory Lifecycle Runbook

## Product boundary

Memory improves continuity only when an elder can inspect, correct, delete, and bound it by consent, purpose, and retention. Family summaries must use care outcomes, not private transcript facts.

## LTM path (mem0 vs analyzer)

- When `MEM0_ENABLED=1`, **long-term recall into the product path is Pi FC `memory` + mem0 adapter only**. Analyzer `MemoryEngine` skips lifecycle L3 vectors so traces do not show “ghost” memories while FC returns empty/`no_dump`.
- When mem0 is off, analyzer may still populate lifecycle L3 for observability / legacy paths; FC recall still uses the lifecycle backend dump policy.
- Empty/timeout mem0 degrade must **not** tell the user they have no granted memories — copy is “记忆服务暂时不可用，稍后再试。” Machine meta stays `reason=mem0_empty_no_dump` / `no_dump=true`.

## Operational checks

1. Confirm `GET /api/memory/memories` returns only `consent_status=granted`, `deletion_state=active`, non-expired memories.
2. Correct one memory with `PATCH /api/memory/memories/{id}/correction`; verify `correction_state=corrected` and embedding state returns to `pending`.
3. Delete one memory with `DELETE /api/memory/memories/{id}`; verify retrieval omits it and any embedding row is marked `deleted`.
4. Run `backfill_embeddings`; if the provider key is unset, expect `provider_unconfigured`, not fabricated embeddings.
5. Run reflection; verify it creates a `memory_reflection_proposals` row and does not mutate `user_profiles` until accepted.
6. Query family summary; verify it contains task status counts and no transcript or memory content.

## Pending external gates

Jurisdiction-specific legal approval, production embedding-provider terms, and pilot retention periods remain pending until selected and documented.
