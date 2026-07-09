# Production Development Plan

## 1. Decision

Build AI Companion Runtime as a production eldercare coordination product. The investor walkthrough is a demonstration of the production pilot environment, not a separate demo implementation.

The first production promise is deliberately narrow:

> An elder can create and complete a care task through conversation or a device; the system can detect defined risk events; an authorized family member can see task outcomes and verified alert delivery; an operator can reconstruct the decision chain.

This promise is valuable only if authorization, persistence, delivery, safety policy, and audit behavior survive dependency failures without silently inventing success.

## 2. Baseline at `a490453`

### Implemented and reusable

- Authenticated WebSocket chat and device protocols route through `AgentHarness`.
- Intent, emotion, risk, memory, personality, prompt building, model routing, tools, and Trace events exist.
- Elder risk categories cover health emergency, scam alert, and emotional low scenarios with tests.
- `CareTask` supports creation, clarification, recurrence, snooze, cancellation, completion, and projection to `Reminder`.
- Reminders persist, schedule, deliver through active device connections, and record acknowledgements/history.
- Family bindings, reminder management, persisted notifications, and role guards exist.
- Web surfaces exist for chat, reminders, notifications, login, and technical traces.
- Firmware and protocol contract tests cover the expected realtime message sequence.
- CI runs backend tests, a narrow Ruff rule set, web build, and a mocked latency regression.

### Production gaps that block external pilots

1. Safety configuration can fail open: invalid or missing risk rules can become a normal low-risk result.
2. Database failure can create an ephemeral session while the product continues to imply durable ownership and audit.
3. Redis failure can silently weaken a distributed rate limit to per-process memory.
4. Trace persistence failure is swallowed even for events used to support audit claims.
5. Family delivery is mainly persisted event plus webhook; provider abstraction, retry policy, idempotency, receipt states, and escalation ownership are incomplete.
6. Device transport lacks a complete field-security contract for identity, TLS, provisioning, signed updates, rotation, and revocation.
7. Reflection and long-term vector-memory lifecycle contain placeholders and do not yet support a trustworthy personalization loop.
8. Frontend role separation, accessibility, behavioral tests, and operator/care workflows are incomplete.
9. Deployment configuration and operational readiness remain development-oriented.

## 3. Product and domain boundaries

### Canonical domains

| Domain | Owns | Does not own |
|---|---|---|
| Identity and consent | users, roles, family bindings, permissions, consent grants, revocation | client-side route gating as authorization |
| Care plan | `CareTask` intent, lifecycle, confirmation, completion, snooze, cancellation | timer transport details |
| Scheduling and delivery | `Reminder` projection, next-fire calculation, attempts, acknowledgements | care meaning or medication truth |
| Safety policy | risk rules, policy versions, evidence, action decision, human escalation | medical diagnosis |
| Notification | recipient resolution, attempts, provider status, receipts, retries, escalation | declaring delivery before receipt |
| Conversation | messages, streaming response, tool request, task clarification | silent care mutations |
| Memory | consented facts, provenance, retention, correction, deletion, retrieval | unrestricted transcript sharing |
| Device fleet | device identity, session, capability, update, health, command receipt | family authorization policy |
| Audit and operations | immutable critical events, case timeline, incident evidence | substituting telemetry for required records |

`CareTask` is the source of truth for medication and appointment workflows. `Reminder` remains a scheduling projection. New features must not create a third competing task model.

### Safety product boundary

- The system may identify configured patterns and recommend a safe next action.
- It must use calibrated language and preserve the evidence/policy version behind the action.
- It must not claim diagnosis, guaranteed scam detection, guaranteed emergency response, or verified family contact without delivery evidence.
- High-risk automation must expose a human fallback and an explicit “not delivered / not confirmed” state.

## 4. Target production architecture

### Request path

1. Gateway authenticates user or device, applies size/rate/admission limits, and assigns a trace and idempotency context.
2. Session service loads a durable session or returns an explicit degraded/unavailable result according to policy.
3. Safety, intent, emotion, and memory analysis run with bounded deadlines and structured outcomes.
4. Safety policy resolves a versioned action before any experimental runtime or unrestricted tool execution.
5. Conversation runtime streams a response while domain commands execute through idempotent services.
6. Care commands mutate `CareTask`; scheduling projects to `Reminder`; notification commands create an outbox event.
7. Workers deliver reminders/notifications, persist attempts and receipts, and open an operator case when policy requires human ownership.
8. Critical audit events are durably recorded; optional telemetry may fail soft only when the product clearly distinguishes it from audit.

### Deployment shape

- API instances remain stateless except for bounded connection state.
- PostgreSQL is the source of truth for identity, care, delivery, consent, and critical audit records.
- Redis is an acceleration and coordination dependency with explicit production failure policies, not an invisible correctness substitute.
- Celery workers are separated by workload class: reminders, notifications, memory, and maintenance.
- Provider integrations sit behind narrow adapters with idempotency keys, timeout budgets, retries, and receipt normalization.
- Device connections use device identity and revocable credentials distinct from elder account JWTs.
- OpenTelemetry exports service telemetry; critical care/audit records remain in the transactional domain store.

## 5. Production requirements

### Safety and reliability invariants

- Missing/invalid risk policy cannot produce `low`; production startup fails or risk-dependent requests return an explicit safety-unavailable response.
- A care mutation has one idempotency key and one durable result.
- No UI or assistant copy says delivered, notified, completed, or acknowledged without matching persisted state.
- A failed database write cannot be hidden behind a successful chat/task outcome.
- Rate limiting remains meaningful across instances; a coordination outage has a configured fail-closed or load-shed policy.
- Critical audit events are either committed with the domain transaction or the action is marked unaudited and blocked where policy requires audit.
- Every automated escalation has an owner, deadline, and terminal resolution.

### Initial service objectives

These are starting product objectives, to be validated during pilot rather than marketed as achieved:

| Measure | Initial objective | Evidence |
|---|---:|---|
| API availability | 99.9% monthly, excluding announced maintenance | external uptime and server metrics |
| Chat first response | p95 <= 1.5s text path; p95 <= 2.5s device voice path after final transcript | production traces, not mocks |
| Care mutation durability | 99.99% accepted commands have one durable terminal state | DB reconciliation job |
| Reminder dispatch | 99.9% due reminders create an attempt within 60s | scheduler and attempt tables |
| Alert provider acceptance | p95 <= 30s for high/critical events | normalized provider receipt |
| Audit completeness | 100% of policy-triggered care/safety actions have actor, policy version, input reference, decision, and outcome | audit query |
| Device fleet health | 99% of enrolled devices report health within the configured interval | fleet heartbeat dashboard |

### Privacy and consent

- Collect the minimum data needed for the active care purpose.
- Treat health, biometric/voice, precise location, emergency-contact, and longitudinal behavior data as sensitive.
- Record consent purpose, scope, actor, time, version, expiry, and revocation.
- Separate elder private conversation from family-visible care outcomes.
- Support access, correction, export, deletion, and retention policies by data category.
- Encrypt data in transit and at rest; isolate secrets; log privileged access.
- Complete jurisdiction-specific legal review before external launch. The initial deployment country and pilot organization must be selected before finalizing retention and incident procedures.

### Security baseline

- Threat-model elder, family, operator, provider, model/tool, device, and supply-chain boundaries.
- Enforce server-side RBAC/permission checks for every family and operator action.
- Move browser auth from long-lived JavaScript-readable tokens toward secure session handling with rotation, logout revocation, and CSRF controls where applicable.
- Add request/frame size limits, audio duration limits, concurrency limits, and abuse budgets to WebSocket/device paths.
- Add device identity, secure provisioning, credential rotation/revocation, TLS validation, secure boot, signed firmware, update rollback, and vulnerability response.
- Pin and scan dependencies and images; generate an SBOM for releases; protect production configuration from sample credentials.

### AI and tool governance

- Version prompts, models, risk rules, tool schemas, and response policies.
- Maintain offline evaluation sets for safety false negatives/positives, task extraction, ambiguous mutation, scam language, health language, and family-summary privacy.
- Shadow-test model/rule changes before promotion and support rollback by version.
- Treat model output as untrusted input to tools; validate schema, authorization, target identity, time, and mutation scope.
- Do not store memories without provenance, consent scope, correction path, and retention class.

## 6. Delivery roadmap

Each phase must close data, API/service, frontend/device, tests, operations, and documentation. A backend-only or UI-only phase is incomplete.

### Phase 0: Production contract and fail-safe foundation

**Exit condition:** the system cannot silently claim safety, durability, rate limiting, or audit when the relevant dependency has failed.

1. **PR-01: Fail-closed risk policy**
   - Validate rule schema and version at startup.
   - Return explicit safety-unavailable behavior in non-startup reload failures.
   - Add missing/invalid/empty-rule production tests and health reporting.
2. **PR-02: Durable session contract**
   - Remove unconditional ephemeral session fallback in production.
   - Add explicit development-only mode and surface degraded state to clients.
   - Test DB outage across chat and device paths.
3. **PR-03: Distributed admission control**
   - Define Redis outage policy, add WebSocket/audio size and concurrency controls, and test multi-instance semantics.
4. **PR-04: Critical audit boundary**
   - Classify critical audit versus optional telemetry.
   - Make required audit writes transactional or block the policy action with an explicit status.
5. **PR-05: Release configuration hardening**
   - Separate development compose from production manifests; require secret injection, TLS endpoints, migration job, backups, and restore verification.

### Phase 1: Complete care-task closed loop

**Exit condition:** an elder or family member can create, clarify, deliver, acknowledge, snooze, complete, and audit one care task through real production paths.

6. **PR-06: CareTask API as canonical domain**
   - Expose typed create/list/update/clarify/complete/snooze/cancel endpoints.
   - Keep reminder creation internal to projection logic.
   - Add optimistic concurrency/version checks and idempotency keys.
7. **PR-07: Delivery-attempt model**
   - Persist reminder attempts separately from task state.
   - Track queued, sent, device-received, played, acknowledged, failed, and expired states.
8. **PR-08: Scheduler concurrency and recovery**
   - Add row locking/lease semantics, retry policy, dead-letter handling, reconciliation, and timezone/DST tests.
9. **PR-09: Elder “Today” experience**
   - Implement the elder role shell, today list, large targets, clarification, confirmation, and offline/pending states from `DESIGN.md`.
10. **PR-10: Family care management**
    - Implement family overview/tasks with binding permissions and minimal-necessary content.
    - Add frontend behavioral tests for authorization, task lifecycle, and errors.
11. **PR-11: Device receipt loop**
    - Persist device command receipt and audio playback acknowledgement.
    - Add real-board evidence capture with firmware version, device ID, timestamp, and trace/task IDs.

### Phase 2: Verified safety escalation and family coordination

**Exit condition:** a configured risk event creates an auditable case and reaches the correct human channel with a normalized delivery outcome.

12. **PR-12: Versioned safety decision record**
    - Persist policy version, category, level, evidence references, negation/safe-context result, action, and confidence/calibration metadata.
13. **PR-13: Notification outbox and idempotency**
    - Commit alert plus outbox atomically; add retries, deduplication, dead-letter state, and reconciliation.
14. **PR-14: Provider adapters and receipts**
    - Start with one production channel suitable for the pilot, then add a second independent channel.
    - Normalize accepted, delivered, read, failed, expired, and unknown.
15. **PR-15: Escalation policy and operator case**
    - Resolve recipients by priority and availability; define timeout escalation and manual ownership.
16. **PR-16: Family alert experience**
    - Show event, safe summary, recipient attempts, confirmed delivery, next action, and resolution without exposing private transcript content.
17. **PR-17: Safety evaluation gate**
    - Add versioned datasets, threshold reports, adversarial language cases, and release-blocking regression criteria.

### Phase 3: Device fleet and field operations

**Exit condition:** devices can be securely enrolled, monitored, updated, revoked, and recovered during a multi-home pilot.

18. **PR-18: Device registry and provisioning**
    - Add device identity, ownership, capability, certificate/credential state, and one-time enrollment.
19. **PR-19: Secure transport and session lifecycle**
    - Enforce TLS verification, credential rotation, reconnect backoff, replay protection, command sequence, and bounded buffers.
20. **PR-20: Fleet health and operations**
    - Persist heartbeat, firmware, network, audio, last contact, crash/reboot, and command failures; expose an operator fleet view.
21. **PR-21: Signed OTA and rollback**
    - Add signed firmware verification, staged rollout, health gate, rollback, revocation, and release provenance.
22. **PR-22: Hardware-in-the-loop CI lane**
    - Add protocol contract tests, simulator tests, and scheduled physical-device tests with retained logs/artifacts.

### Phase 4: Consent-driven memory and longitudinal value

**Exit condition:** memory improves continuity while remaining inspectable, correctable, deletable, and bounded by purpose.

23. **PR-23: Memory provenance and consent schema**
    - Add source, purpose, sensitivity, retention, consent grant, confidence, and user-visible correction/deletion state.
24. **PR-24: Embedding lifecycle**
    - Complete embedding generation, vector retrieval, model/version tracking, backfill, archive, and deletion propagation.
25. **PR-25: Reflection proposal workflow**
    - Reflection proposes profile/memory changes; deterministic policy or authorized user review accepts them. No direct opaque profile mutation.
26. **PR-26: Family summary privacy policy**
    - Generate only consented care outcomes and exception trends; add privacy leakage evaluations and revocation tests.

### Phase 5: Pilot operations and scale readiness

**Exit condition:** the team can run a bounded external pilot with measured reliability, incident response, and user support.

27. **PR-27: Observability and SLO dashboards**
    - Add production latency, error, queue, delivery, audit completeness, model/tool, and device-health dashboards with alerts.
28. **PR-28: Backup, restore, and disaster recovery**
    - Automate backups; run restore drills; document RPO/RTO and dependency recovery.
29. **PR-29: Incident and safety operations**
    - Add runbooks for missed reminders, failed alerts, unsafe output, privacy incident, device compromise, and provider outage.
30. **PR-30: Pilot controls**
    - Add cohort enrollment, consent capture, support workflow, feature/config rollout, kill switches, and exit criteria.
31. **PR-31: Production evidence pack**
    - Generate evidence from the pilot environment: release SHA, migration version, SLO window, safety evaluation result, restore drill, device logs, and end-to-end trace/receipt chain.

## 7. Required test strategy

### Unit and property tests

- Time parsing, recurrence, timezone, DST, idempotency, state transitions, recipient policy, permission matrix, policy schema, and receipt normalization.
- Property/state-machine tests for `CareTask` and delivery attempt transitions.

### Integration tests

- PostgreSQL/Redis/Celery with real containers, transactional outbox, worker retry, lock contention, dependency outage, migration upgrade/rollback, and auth revocation.
- Provider sandbox tests for retries, duplicate callbacks, late receipts, signature verification, and permanent failure.

### End-to-end tests

- Elder creates ambiguous medication task, clarifies it, device receives and plays it, elder acknowledges, family sees the verified outcome.
- High-risk scam/health phrase produces a decision record, safe response, notification attempts/receipt, and operator resolution.
- Unauthorized family member cannot view or mutate another elder’s data.
- Database, Redis, provider, model, ASR, and device failures produce explicit states without invented success.

### Non-functional tests

- Load/soak for concurrent WebSockets, scheduler bursts, provider outage, and reconnect storms.
- Security tests for auth/session, prompt/tool injection, payload limits, replay, credential rotation, and firmware update validation.
- Accessibility tests plus manual screen-reader, keyboard, zoom, touch-target, and cognitive walkthroughs.
- Hardware tests with real device logs, not annotated expected output alone.

## 8. Production definition of done

A feature is production-complete only when:

- Domain ownership and state transitions are documented.
- Schema and migrations support upgrade and rollback.
- API/tool/device contracts are typed, authorized, idempotent, and versioned where needed.
- Elder, family, device, and operator surfaces expose truthful states.
- Happy path, failure path, permission path, and dependency-outage tests pass.
- Metrics, logs, critical audit, alerting, and runbooks exist.
- Privacy purpose, retention, access, correction, deletion, and consent behavior are defined.
- Deployment, rollback, and data recovery are exercised.
- Evidence is captured from the same production/pilot path shown to investors.

## 9. Investor walkthrough of production state

The walkthrough should use a dedicated pilot tenant and real product roles, but no special product behavior:

1. Elder creates a medication task through conversation or device.
2. The system requests clarification rather than guessing when multiple tasks match.
3. The task appears in the elder’s Today view and the authorized family dashboard.
4. A real device or verified simulator receives the scheduled event and returns receipt states.
5. A configured scam or health-risk sentence creates a versioned safety decision and family notification attempt.
6. The family view shows the provider receipt and next action.
7. The operator opens the linked trace/case and reconstructs policy, model/tool, task, and delivery events.
8. The team shows current SLO and evaluation evidence with an explicit date and release SHA.

Seeded pilot accounts and data-reset tooling are acceptable test operations. They must be access-controlled, disabled in production tenants, dry-run by default, audited, and incapable of bypassing normal product authorization or state transitions.

## 10. Sequence and team focus

For the next development cycle, complete Phase 0 before adding new end-user promises. Then finish one vertical care-task loop in Phase 1 before expanding memory, voice cloning, phone integration, or additional model runtimes.

Recommended ownership:

| Lane | Immediate responsibility |
|---|---|
| Backend/runtime | PR-01 through PR-04, then CareTask API and outbox |
| Web/product | role shells, elder Today, family tasks/alerts, accessibility tests |
| Device | receipt contract, identity/provisioning design, real-board evidence |
| Safety/data | policy schema, evaluation set, consent and retention model |
| Platform/ops | production deployment, CI integration tests, dashboards, restore drills |

Do not run all lanes as speculative platform work. Each PR must advance a named production invariant or a complete user flow.

## 11. Standards and evidence basis

The plan uses the following external baselines as engineering inputs, not as claims of certification or compliance:

- NIST AI RMF 1.0 and the Generative AI Profile: govern, map, measure, and manage AI risk throughout the lifecycle.
- WHO guidance on ethics and governance of AI for health: protect autonomy, safety, transparency, accountability, inclusiveness, and sustainability.
- NISTIR 8259A: define device identification, configuration, data protection, interface access, software update, and cybersecurity-state awareness.
- W3C WCAG 2.2: accessibility target for family and operator web surfaces.
- OWASP ASVS: application-security verification baseline.
- OpenTelemetry semantic conventions: consistent service telemetry; domain audit remains separately persisted.
- FDA Clinical Decision Support guidance and local legal review: maintain a clear boundary between care coordination and regulated diagnosis/treatment claims.
- China’s Personal Information Protection Law, plus the laws and rules of the selected deployment jurisdiction: determine sensitive-data, consent, cross-border, retention, and incident obligations.

Reference URLs:

- https://www.nist.gov/itl/ai-risk-management-framework
- https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence
- https://www.who.int/publications/i/item/9789240029200
- https://csrc.nist.gov/pubs/ir/8259/a/final
- https://www.w3.org/TR/WCAG22/
- https://owasp.org/www-project-application-security-verification-standard/
- https://opentelemetry.io/docs/specs/semconv/
- https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software
- https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm

## 12. Open decisions before external pilot

- Deployment jurisdiction and legal entity responsible for personal data.
- Pilot partner, cohort size, staffed support/escalation hours, and emergency disclaimer.
- First production notification channels and provider SLAs.
- Device hardware SKU, provisioning trust model, and OTA signing ownership.
- Data retention periods by conversation, care task, safety event, audio, memory, and audit record.
- Safety thresholds and who approves policy/model releases.
