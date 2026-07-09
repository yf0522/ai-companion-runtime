# Memory Lifecycle Runbook

## Product boundary

Memory improves continuity only when an elder can inspect, correct, delete, and bound it by consent, purpose, and retention. Family summaries must use care outcomes, not private transcript facts.

## Operational checks

1. Confirm `GET /api/memory/memories` returns only `consent_status=granted`, `deletion_state=active`, non-expired memories.
2. Correct one memory with `PATCH /api/memory/memories/{id}/correction`; verify `correction_state=corrected` and embedding state returns to `pending`.
3. Delete one memory with `DELETE /api/memory/memories/{id}`; verify retrieval omits it and any embedding row is marked `deleted`.
4. Run `backfill_embeddings`; if the provider key is unset, expect `provider_unconfigured`, not fabricated embeddings.
5. Run reflection; verify it creates a `memory_reflection_proposals` row and does not mutate `user_profiles` until accepted.
6. Query family summary; verify it contains task status counts and no transcript or memory content.

## Pending external gates

Jurisdiction-specific legal approval, production embedding-provider terms, and pilot retention periods remain pending until selected and documented.
