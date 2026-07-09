# Product Roadmap: Verified Home-Care Coordination

## 1. Decision

AI Companion Runtime should develop into a family-funded home-care coordination product, delivered through a calm elder companion.

The product is not primarily a chatbot. Conversation is the easiest way for an elder to create a task, confirm an outcome, ask for help, or express a concern. The accountable product is the closed loop behind that conversation:

> agreed care task -> delivery -> elder acknowledgement -> verified exception -> human ownership -> resolution evidence

The first commercial unit is one household: one elder, one or two authorized caregivers, one companion endpoint, a small care plan, verified contacts, and defined escalation rules.

This document supersedes the sequencing in `docs/production-development-plan.md` after the production-accountability baseline merged at `fa7d9b9`. That earlier document remains the architectural foundation and definition of done.

## 2. Why this product shape

Three directions were considered.

| Direction | Advantage | Failure mode | Decision |
|---|---|---|---|
| Companion chat first | Fast onboarding and emotionally legible demos | Weak willingness to pay, difficult outcome measurement, easy substitution by general assistants | Keep as interaction layer, not the product center |
| Institution operations first | Higher contract value and clear staff workflows | Long sales cycle, integration burden, jurisdiction-specific delivery, and premature multi-tenant complexity | Defer until household workflow is proven |
| Family-funded home-care coordination | Existing code already supports tasks, safety, family, devices, and operators; buyer and beneficiary are distinct but understandable | Requires consent, real notification delivery, and disciplined human operations | Primary direction |

The value proposition is:

- Elder: “Help me remember and complete today’s agreed tasks without making me feel monitored.”
- Family: “Tell me when attention is actually needed, show what happened, and do not expose private conversation by default.”
- Operator: “Give every unresolved exception an owner, deadline, evidence trail, and resolution path.”

## 3. What the current baseline proves

Observed at `fa7d9b9`:

- `CareTask` is the canonical care entity with idempotency, version checks, clarification, completion, snooze, and cancellation.
- `Reminder` projects a care task into scheduling and device delivery.
- Risk handling is fail-closed and high-risk responses are prioritized ahead of optional observability work.
- Safety decisions, notification outbox rows, delivery attempts, normalized receipt records, and basic operator cases are persisted. The current provider path is sandbox/unconfigured, so this proves contract primitives rather than production delivery.
- Device enrollment, revocation, sequence handling, receipts, and fleet records exist.
- Memory has consent, provenance, correction, deletion, and reflection proposal primitives.
- Elder, family, care-operator, and reliability-operator surfaces exist.
- Production contracts, latency checks, deployment examples, backup checks, and evidence tooling exist.

This is enough to support a serious pilot architecture. It is not yet a pilot-grade normal-user journey: role self-registration remains open, family binding codes are in memory, notification providers are sandbox/unconfigured, and household consent/contact verification are incomplete.

## 4. Lessons from implementation

### 4.1 Safety latency is a product behavior

The latency regression exposed synchronous Trace serialization and request-time YAML parsing before a high-risk reply. Moving those operations out of the response-critical path reduced the high-risk benchmark from approximately 11.1 ms to 8.6-8.8 ms in the mocked runtime.

Rule: safety response, user-visible acknowledgement, and durable action ownership stay on the critical path. Optional telemetry, summarization, and enrichment stay off it.

### 4.2 Persisted does not mean delivered

An outbox row proves intent to notify. A provider acceptance proves handoff. A delivery receipt proves provider-reported delivery. A read or human confirmation is a different state again.

Rule: UI and model copy must never collapse queued, accepted, delivered, read, acknowledged, and resolved into “已通知”.

### 4.3 Fail-closed needs an operating mode

Treating a missing risk engine as critical is safer than proceeding normally, but repeated false critical events can make the service unusable.

Rule: fail-closed behavior must include an explicit `safety_unavailable` state, operator alert, user-safe copy, recovery probe, and incident metric. Do not silently convert it to low risk and do not present it as a real detected crisis.

### 4.4 Domain boundaries must reach the UI

The backend establishes `CareTask` as the business object and `Reminder` as its projection, but family UI still exposes Reminder implementation language.

Rule: new family and elder flows use care-task vocabulary and APIs. Reminder APIs become internal or compatibility surfaces.

### 4.5 Audit is not the same as observability

Traces help engineering investigate. Critical decisions, consent changes, delivery attempts, contact attempts, and case resolutions are business records.

Rule: required audit records have explicit retention, authorization, and failure semantics. They are not best-effort Trace events.

### 4.6 A production demo is an operational slice

The strongest demonstration is not more generated conversation. It is a real household lifecycle using normal authorization and persistence:

1. Elder grants a defined sharing scope and verifies a caregiver.
2. Caregiver creates an agreed medication task.
3. The companion endpoint delivers it and receives an acknowledgement.
4. A missed acknowledgement creates an exception according to policy.
5. A verified channel reaches the caregiver.
6. An operator can own and resolve the case.
7. The elder can see what was shared and revoke future sharing.

## 5. Product boundaries

### In scope for the first paid pilot

- Medication, appointment, hydration, exercise, and routine care tasks based on a user- or caregiver-defined schedule.
- Elder acknowledgement, snooze, completion, and “I need help” responses.
- Missed-task exceptions based on explicit policy, not medical inference.
- Defined scam-language friction and caregiver verification workflows.
- Emotional-crisis and health-emergency guidance with human escalation paths.
- Minimum-necessary family summaries based on care outcomes.
- Device health, notification receipt, and operator case visibility.

### Not in scope

- Diagnosis, symptom interpretation, dose changes, treatment recommendations, or drug interaction advice.
- Guaranteed scam detection or autonomous financial decisions.
- Autonomous emergency-service dispatch.
- Operating-system phone or message interception without a separately verified integration.
- Unrestricted family access to transcripts, memories, or inferred emotional history.
- Voice cloning in the initial pilot.
- A general institution management suite before the household workflow is proven.

Any feature that changes these boundaries requires product, safety, legal, and architecture review before implementation.

## 6. North-star model

### North-star outcome

**Verified Care Loop Rate**

The percentage of due care-task occurrences that reach a truthful terminal outcome within policy:

- completed or acknowledged by the elder;
- intentionally snoozed or declined;
- converted into an owned exception and resolved;
- explicitly expired or failed with evidence.

Unknown, silently dropped, or falsely successful occurrences do not count.

### Supporting metrics

| Metric | Initial pilot target | Reason |
|---|---:|---|
| Household readiness completion | >= 90% of invited households without engineer intervention | Proves onboarding is a product |
| Due-task terminal outcome | >= 95% within the task policy window | Measures the full care loop |
| Device command receipt | >= 99% when device is online | Separates transport from human behavior |
| Notification provider accepted | >= 99% for configured contacts | Proves handoff reliability |
| High-severity case owner assigned | p95 <= 5 minutes during staffed hours | Makes escalation accountable |
| False high-risk escalation | Measured by category; release cannot worsen approved baseline | Prevents alert fatigue |
| Family notifications per household | Bounded by policy; monitor acknowledgement and mute rates | Optimizes signal, not volume |
| Elder consent/correction requests | 100% auditable and actionable | Measures agency and trust |

Chat turns, session duration, token volume, and daily active use are diagnostics. They are not primary success metrics.

## 7. Core product journeys

### 7.1 Household activation

1. Account is invited or created for a named role.
2. Elder reviews who is joining the care circle and what each permission means.
3. Caregiver and emergency contacts verify their channels.
4. Elder grants task, notification, and summary scopes separately.
5. Companion endpoint is enrolled and its health is visible.
6. A notification test and task-delivery test complete.
7. Household becomes `pilot_ready` only when required checks pass.

### 7.2 Daily care loop

1. Elder or caregiver creates an agreed `CareTask`.
2. Ambiguity causes clarification, never guessing.
3. The next occurrence appears in Elder Today and Family Care Plan.
4. The endpoint reports received and played states.
5. Elder acknowledges, completes, snoozes, declines, or requests help.
6. Policy determines whether an unresolved occurrence becomes an exception.

### 7.3 Safety and scam exception

1. Runtime records category, level, policy version, evidence references, and action.
2. High-risk conversation stops normal generation and gives calibrated safe guidance.
3. Consent and emergency policy resolve the correct human recipient.
4. Outbox and provider receipts remain distinct.
5. A case is created when human ownership is required.
6. Case resolution records attempts, outcome, and reason without exposing unrelated transcript content.

### 7.4 Privacy and correction

1. Elder sees current caregivers, permissions, memories used for care, and recent sharing events.
2. Elder can correct a remembered fact, revoke a scope, remove a caregiver, or request deletion.
3. Revocation affects future access immediately and queues defined deletion work.
4. Family views explain unavailable data instead of encouraging workarounds.

## 8. Target product architecture

The current modular monolith remains the right shape for the first pilot. Do not split services solely for presentation or hypothetical scale.

### Keep in one deployable backend

- identity, care circle, consent, care plan, scheduling, safety policy, notifications, cases, memory lifecycle, device fleet, and audit APIs;
- transactional writes that connect a safety decision to its outbox and case;
- scheduler and worker code sharing the same domain schema.

### Separate runtime processes where failure isolation matters

- API/WebSocket runtime;
- scheduler and delivery workers;
- notification provider worker;
- embedding/reflection workers;
- optional Pi sidecar;
- observability stack.

### Required product-state additions

- `Household` or `CareCircle` as the explicit aggregate for elder, caregivers, contacts, devices, and policy.
- Versioned `ConsentGrant` covering task management, notifications, summaries, memory, and transcript access separately.
- Verified `ContactPoint` with channel, ownership, verification state, availability, priority, and revocation.
- Versioned `EscalationPolicy` with category, severity, delay, recipients, staffed-hours behavior, and stop conditions.
- `CaseActivity` timeline for assignment, contact attempt, note, escalation, and resolution.
- `HouseholdReadinessCheck` derived from configuration and live verification, not a manually set boolean.

Do not add a second task entity, a second notification log, or a separate investor data model.

## 9. Delivery plan

Each PR must close schema, migration, API/service, UI/device, tests, metrics, and runbook changes that belong to its vertical slice. A backend-only feature is not complete.

### Release A: Operable household pilot

**Exit condition:** a household can activate and run a verified care loop through one real notification channel without engineer intervention.

#### PR-A1: Platform readiness truth

- Unify documented frontend API/WebSocket defaults and validate production URLs at startup.
- Add platform readiness for database, Redis, safety rules, migrations, device-identity enforcement, worker heartbeat, and configured provider capability.
- Distinguish `ready`, `degraded`, and `unsafe_to_serve` for the deployment itself.
- Expose machine-readable checks and an operator-only repair view.

Acceptance: a misconfigured deployment cannot report platform-ready; every failed check has an operator-facing repair action. This PR does not claim household pilot readiness.

#### PR-A2: Product-facing CareTask contract

- Move new elder/family UI reads and writes to `CareTask` APIs.
- Keep `Reminder` internal to scheduling, attempts, and device projection.
- Remove implementation-language copy from family pages.
- Expose next occurrence, last outcome, delivery state, confirmation policy, and version conflict states.
- Add migration/compatibility tests for existing reminder-created data.

Acceptance: a family user never needs to understand the Reminder projection to manage care, and later onboarding flows bind permissions to the canonical care object.

#### PR-A3: Care circle onboarding and consent

- Add the household/care-circle aggregate and migration.
- Replace open role self-selection with invite or controlled enrollment for pilot roles.
- Implement caregiver invite, elder acceptance, scoped permission grant, revocation, and audit events.
- Add onboarding UI and route guards.
- Test invitation replay, expired invites, elder denial, permission reduction, and removed caregivers.

Acceptance: a family account cannot see elder data until a persisted, active scope permits it.

#### PR-A4: Verified contacts and one production notification channel

- Add contact CRUD, ownership, verification challenge, priority, quiet-hours/availability, and revocation.
- Implement one provider adapter selected for the deployment jurisdiction.
- Normalize provider acceptance, delivery, failure, expiry, and unknown states.
- Add webhook signature verification, idempotency, retry policy, reconciliation, and provider runbook.

Acceptance: the team can prove a real provider receipt from the same flow used by the product.

#### PR-A5: Escalation policy and accountable cases

- Add versioned escalation policies for missed tasks, scam alerts, emotional crisis, health emergency, device outage, and failed contact.
- Add a `CaseActivity` record and API for assignment, contact attempt, note, escalation, resolution, and reopen events.
- Define allowed state transitions, optimistic concurrency, assignment ownership, due time, staffed-hours behavior, and resolution reasons.
- Build `/ops/care/:caseId` and queue filters by severity, owner, SLA, and state.
- Emit metrics for unowned, overdue, reopened, and delivery-failed cases.
- Test duplicate contact attempts, concurrent assignment, invalid transitions, reopen history, and unstaffed fallback.

Acceptance: every high-severity exception has exactly one current owner or an explicit unstaffed fallback state, and its complete activity timeline is reconstructable from domain records rather than Trace logs.

#### PR-A6: Household pilot readiness

- Add a derived household-readiness evaluator after care circle, consent, contacts, provider, device, care task, and escalation policy exist.
- Require active elder consent, at least one verified caregiver contact, a verified delivery test, enrolled endpoint, current policy, and passing platform readiness.
- Add family and operator readiness views with exact missing prerequisites.
- Prevent `sandbox` and `unconfigured` providers from satisfying household readiness.

Acceptance: a household becomes `pilot_ready` only from verifiable prerequisites; no manual boolean or seeded investor state can bypass them.

### Release B: Low-noise family value

**Exit condition:** family users see a useful exception feed, not a transcript feed or notification firehose.

#### PR-B1: Elder Today as the default home

- Make `/elder/today` the elder landing screen.
- Put next action, acknowledgement, snooze, completion, and help above open conversation.
- Add 48px primary targets, 18px body text, reduced-motion handling, and screen-reader status announcements.
- Support offline/pending idempotent actions and explain unsafe retries.

Acceptance: the full daily care loop passes at 360x800, 200% zoom, keyboard-only, and screen-reader smoke checks.

#### PR-B2: Missed-task exception policy

- Separate transport failure, device offline, played-but-unacknowledged, elder-declined, and unknown.
- Apply grace periods and recurrence-aware escalation.
- Avoid escalating a missed reminder as a medical emergency unless policy explicitly says so.
- Show family and operator the evidence chain and next action.

Acceptance: every missed occurrence has one explainable classification and cannot generate duplicate cases.

#### PR-B3: Family alert receipt timeline

- Show category, calibrated risk wording, recipient, channel, attempts, provider receipts, owner, due time, and resolution.
- Add acknowledgement semantics that do not falsely close an unresolved operator case.
- Add privacy-scope disclosure and elder-visible sharing event.

Acceptance: family UI never says “notified” without at least provider acceptance and always distinguishes delivery from resolution.

#### PR-B4: Household overview and device confidence

- Add next care tasks, open exceptions, last successful acknowledgement, endpoint online state, last seen, and delivery confidence.
- Avoid surveillance metrics such as conversation counts or mood scores.
- Add clear unknown and stale-data states.

Acceptance: a caregiver can answer “is attention needed now?” in under 30 seconds without opening a transcript.

### Release C: Safety quality and field reliability

**Exit condition:** policy/model/device changes have release evidence and field-recovery procedures.

#### PR-C1: Versioned safety evaluation gate

- Build consented, de-identified, versioned evaluation sets for scam, crisis, health emergency, negation, quoted speech, and benign adjacent language.
- Measure false escalation and missed escalation separately by category.
- Record policy/model/prompt version and threshold decisions.
- Block releases that regress approved safety limits.

Acceptance: every safety release has a dated report, release SHA, dataset version, reviewer, and rollback decision.

#### PR-C2: Speech-path reliability

- Define explicit ASR/TTS dependency states instead of empty-text or silent fallback behavior.
- Add provider timeout, cancellation, retry-safe boundaries, audio validation, and user-visible recovery.
- Keep text and physical acknowledgement available when voice fails.
- Add noisy-audio, partial-transcript, reconnect, and provider-outage tests.

Acceptance: a voice outage degrades to a truthful alternate interaction without inventing task completion.

#### PR-C3: Device fleet operations

- Complete certificate/credential rotation, secure provisioning, signed OTA evidence, rollback, device health, and revocation workflows.
- Add hardware-in-the-loop evidence for receive, play, acknowledge, reconnect, and update rollback.
- Add family-visible device state and operator repair playbook.

Acceptance: a device can be enrolled, diagnosed, rotated, updated, rolled back, and revoked without a database edit.

### Release D: Consent-driven personalization

**Exit condition:** personalization improves care interaction without creating invisible profiles or uncontrolled sharing.

#### PR-D1: Privacy center

- Add elder-visible memory, sharing scope, caregivers, consent history, export, correction, deletion, and revocation.
- Add reason-for-access and provenance for sensitive facts.
- Separate care-outcome summary permission from transcript permission.

Acceptance: the elder can understand and change what the system remembers and shares without operator assistance.

#### PR-D2: Reviewable reflection

- Generate proposed preferences or stable facts with source references and confidence.
- Require review for sensitive or care-affecting changes.
- Prevent reflections from changing medication, emergency, or escalation policy.
- Add expiry and contradiction handling.

Acceptance: no inferred memory becomes a care instruction without explicit authorization.

#### PR-D3: Family summary validation

- Interview at least five elders and five caregivers before adding new longitudinal insights.
- Restrict summaries to consented care outcomes and actionable changes.
- Measure usefulness, discomfort, correction rate, and notification reduction.

Acceptance: summary scope is validated by users and has a correction path; engagement language is not used as a proxy for wellbeing.

## 10. Product validation work alongside engineering

Engineering should not guess the care workflow alone.

### Before Release A closes

- Conduct five elder and five family-caregiver interviews.
- Test invite, permission, missed-task, scam-warning, and alert-receipt concepts.
- Shadow at least two real care-coordination routines with consent.
- Confirm first notification channel, staffed hours, and escalation owner.
- Review health and crisis language with qualified local legal/safety advisors.

### Pilot cohort

- Start with 5-10 households, not a public launch.
- Use explicit inclusion/exclusion criteria and a named support owner.
- Record device, provider, policy, model, and release versions per household.
- Hold weekly incident and near-miss review.
- Do not use pilot participants to validate unapproved emergency promises.

## 11. VC and diligence demonstration

The investor demonstration is the production pilot path, not a separate feature set.

### Core demonstration

1. Show household readiness and consent scopes.
2. Create a medication care task by voice or text.
3. Show clarification instead of guessing.
4. Show device receipt and elder acknowledgement.
5. Trigger a scripted scam-risk statement.
6. Show the versioned safety decision and safe response.
7. Show a real provider receipt to an authorized caregiver.
8. Show the operator case owner, attempts, and resolution.
9. Show the elder-visible sharing record and revocation control.
10. Show the release SHA, latency/SLO evidence, safety evaluation version, and known limitations.

### What this proves

- A complete product loop across elder, family, device, notification, operator, and audit surfaces.
- Defensibility in runtime orchestration, care-state integrity, policy governance, device integration, and operational data.
- A path to household subscription and later care-provider distribution without pretending the model itself is the moat.

### Claims to avoid

- “Prevents suicide,” “detects all scams,” “guarantees medication adherence,” or “replaces caregivers.”
- “Family was notified” when the evidence is only an outbox row.
- “Production device” when the path used a simulator without a visible label.
- “HIPAA compliant,” “medical grade,” or equivalent certification language without formal scope and evidence.

## 12. What not to build next

- More model providers unless a measured reliability, cost, or jurisdiction requirement demands one.
- Voice cloning.
- Generic mood dashboards or emotion-score trends for family users.
- Phone interception claims.
- More memory layers before consent and correction UX ships.
- A second task/reminder abstraction.
- A microservice split.
- Institution billing, staffing, or CRM features before household pilot retention and care-loop reliability are known.
- Investor-only seeded behavior that bypasses authorization or normal state transitions.

## 13. Definition of ready for a paid pilot

All of the following are required:

- Selected jurisdiction, privacy owner, incident owner, and staffed escalation hours are documented.
- Household onboarding, consent, contact verification, and device enrollment work without engineer intervention.
- At least one real notification provider has signed webhooks, receipts, retries, reconciliation, and a runbook.
- CareTask is the product-facing care contract and all visible states are truthful.
- High-severity cases have assignment, SLA, attempt timeline, and resolution semantics.
- Safety evaluation and latency regression gates pass for the release SHA.
- Backup restore, worker recovery, provider outage, database outage, Redis outage, and device reconnect drills have dated evidence.
- Elder and family flows pass mobile, accessibility, permission, offline, and dependency-failure tests.
- The pilot cohort has support, consent, exclusion, incident, and exit procedures.

## 14. Evidence basis

These sources guide product and engineering boundaries; they are not claims of certification:

- NIST AI Risk Management Framework and Playbook: lifecycle governance, measurement, monitoring, incident handling, override, and documentation.  
  https://www.nist.gov/itl/ai-risk-management-framework  
  https://airc.nist.gov/docs/AI_RMF_Playbook.pdf
- NIST AI 800-4: post-deployment AI monitoring and incident evidence.  
  https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.800-4.pdf
- WHO AI-for-health guidance: autonomy, safety, transparency, expert supervision, and rigorous evaluation.  
  https://www.who.int/publications/i/item/9789240029200  
  https://www.who.int/publications/i/item/9789240084759
- FDA device software guidance: regulatory analysis depends on the software function, not its marketing label or platform.  
  https://www.fda.gov/medical-devices/digital-health-center-excellence/device-software-functions-including-mobile-medical-applications
- HHS guidance on family disclosure: share information relevant to care with agreement, authorization, or applicable professional/legal grounds.  
  https://www.hhs.gov/hipaa/for-professionals/faq/disclosures-to-family-and-friends/index.html
- FTC older-adult scam guidance: urgency, impersonation, “protect your money,” gift cards, crypto, and unusual payment instructions are high-value friction points.  
  https://consumer.ftc.gov/features/addressing-scams-affecting-older-adults  
  https://consumer.ftc.gov/all-scams/scams-against-older-adults
- FTC health privacy guidance: consumer health apps may remain subject to FTC privacy, security, and breach requirements even when HIPAA does not apply.  
  https://www.ftc.gov/business-guidance/privacy-security/health-privacy
- 988 Lifeline guidance: crisis support requires a live human path; immediate danger requires emergency services appropriate to the deployment jurisdiction.  
  https://988lifeline.org/get-help/what-to-expect/
- W3C WCAG 2.2: current testable web-accessibility baseline, with direct relevance to older users.  
  https://www.w3.org/TR/WCAG22/
- China Personal Information Protection Law and local rules for the chosen deployment: sensitive information, purpose, consent, sharing, retention, and cross-border handling require jurisdiction-specific review.  
  https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm

## 15. Immediate next PR order

1. PR-A1 Platform readiness truth.
2. PR-A2 Product-facing CareTask contract.
3. PR-A3 Care circle onboarding and consent.
4. PR-A4 Verified contacts and one production notification channel.
5. PR-A5 Escalation policy and accountable cases.
6. PR-A6 Household pilot readiness.
7. PR-B1 Elder Today as the default home.
8. PR-B2 Missed-task exception policy.
9. PR-B3 Family alert receipt timeline.
10. PR-C1 Versioned safety evaluation gate.

Do not start Release D personalization work until Release A is operating with real households and Release B has demonstrated low-noise family value.
