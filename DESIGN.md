# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-07-10
- Primary product surfaces: elder companion, family care dashboard, device experience, care operations, operator observability.
- Evidence reviewed: production baseline `fa7d9b9`; `README.md`; `apps/web/app`; `apps/web/components`; `apps/web/stores`; `apps/api/app/api`; `apps/api/app/runtime`; `apps/api/app/db`; `firmware`; `docs/product-roadmap-2026-h2.md`; `docs/device-test.md`; `docs/investor-demo.md`.
- Product rule: the investor walkthrough must use normal authorization, persistence, delivery, and audit paths. Until controlled enrollment and household consent ship, current self-registration and in-memory binding are development-only evidence and must not be presented as pilot-grade onboarding. There is no investor-only product behavior or UI that claims unshipped capability.

## Product thesis
- Category: family-funded home-care coordination, delivered through a calm elder companion.
- Buyer: an adult child or family caregiver who needs reliable exception awareness without continuous surveillance.
- Daily user: an elder who needs a low-friction way to remember, confirm, ask for help, and stay connected.
- Product promise: help the elder complete agreed daily care tasks; tell the right person when a verified exception needs attention; preserve the elder's privacy and agency.
- Interaction model: conversation is the input and support layer. `CareTask`, safety decisions, delivery receipts, consent, and operator cases are the accountable product state.
- Initial wedge: one household, one elder, one or two caregivers, one companion endpoint, medication/appointment/routine tasks, and defined scam or wellbeing escalations.
- Expansion order: household pilot, then multi-household care operations, then institutional integrations. Do not start with a generic institution dashboard or an unlimited social companion.

## Brand
- Personality: calm, respectful, patient, concrete, and dependable. The product should feel like a capable care service, not a novelty chatbot.
- Trust signals: clear identity and role, explicit task confirmations, visible notification state, human escalation status, data-use explanations, and traceable changes.
- Avoid: infantilizing language, fear-based urgency, medical authority claims, generic AI gradients, tool-showcase copy, hidden automation, and mock evidence presented as a live product.

## Product goals
- Goals:
  - Help an elder complete daily care tasks with low-friction voice or text interaction.
  - Detect defined safety risks and escalate them through auditable, policy-controlled workflows.
  - Give authorized family members the minimum necessary care status without exposing private conversations by default.
  - Give operators enough evidence to investigate delivery, safety, model, and device failures.
  - Turn daily care outcomes into a low-noise family exception feed rather than a surveillance feed.
  - Preserve a clear path from every high-stakes automation to a named human owner.
- Non-goals:
  - Diagnose disease, prescribe treatment, replace emergency services, or guarantee prevention of harm.
  - Intercept phone calls or messages at the operating-system level unless a separately shipped integration proves that capability.
  - Use cloned family voices without explicit consent, revocation, provenance, and abuse controls.
  - Build a presentation-only mode that bypasses production authorization, persistence, delivery, or audit paths.
  - Give family members unrestricted access to chat transcripts, inferred mood history, or private memories.
  - Change medication dosage, diagnose conditions, recommend treatment, execute payments, intercept calls, or contact emergency services autonomously.
- Success signals:
  - Care tasks are created, clarified, delivered, acknowledged, snoozed, completed, and escalated without silent state loss.
  - Family alerts show recipient, channel, attempt, receipt, and final status.
  - Critical safety configuration failures prevent unsafe service startup or produce an explicit unavailable state.
  - Elder and family workflows are usable on a phone without operator terminology.
  - A household can complete onboarding, caregiver verification, consent, contact verification, device enrollment, and its first care task without engineer intervention.
  - Family users receive fewer but more actionable notifications, each with an owner, receipt state, and next action.

## Personas and jobs
- Primary personas:
  - Elder: talks with the companion, creates and acknowledges care tasks, asks for help, and receives clear safety guidance.
  - Family caregiver: manages authorized care plans, sees exceptions and delivery outcomes, and responds to escalations.
  - Care operator: handles unresolved alerts, device problems, account recovery, and policy exceptions.
  - Reliability/safety operator: investigates traces, model decisions, notification delivery, and service health.
- User jobs:
  - Elder: “Remind me and help me confirm what I need to do next.”
  - Family caregiver: “Tell me only when attention is needed, and show what happened.”
  - Operator: “Resolve a care or device failure without reading unrelated private content.”
  - Reliability/safety operator: “Reconstruct the decision and delivery chain from evidence.”
- Key contexts of use: voice-first device at home, mobile web for family, low connectivity, noisy audio, repeated or ambiguous requests, stressful health or scam situations, and shared-device privacy constraints.

## Information architecture
- Primary navigation:
  - Elder: today, companion, help, permissions.
  - Family: home, care plan, alerts, people and permissions, privacy.
  - Care operations: case queue, household/device status, case timeline, contact attempts, playbooks.
  - Reliability/safety operations: traces, service health, policy versions, model/tool delivery diagnostics.
- Core routes/screens:
  - `/elder/companion`: production conversation and task interaction.
  - `/elder/today`: current tasks, due status, and simple completion history.
  - `/family/overview`: exceptions, next tasks, recent acknowledgements, and device status.
  - `/family/tasks`: create and manage care tasks; `CareTask` is the business entity and `Reminder` is its scheduling projection.
  - `/family/alerts`: risk events, notification attempts, receipts, and resolution.
  - `/family/summary`: consented, minimum-necessary care summary; never a private chat transcript by default.
  - `/family/people`: caregiver roles, verified contacts, permissions, availability, and escalation order.
  - `/family/privacy`: elder-visible sharing scope, consent history, memory controls, export, and revocation.
  - `/ops/care`: operational cases and manual escalation.
  - `/ops/care/:caseId`: one accountable case timeline with assignment, attempts, evidence, next action, and resolution reason.
  - `/ops/households/:householdId`: service state, contacts, devices, open exceptions, and consent status without unrelated conversation content.
  - `/ops/traces/:traceId`: technical trace, latency, model, tool, and policy evidence.
  - Current `/chat`, `/reminders`, `/notifications`, and `/traces/:traceId` routes migrate into these role shells rather than being duplicated.
- Content hierarchy:
  - Elder: next action, confirmation, help, conversation.
  - Family: exceptions first, then due tasks and trends, then configuration.
  - Operators: unresolved severity and service impact first, then evidence and controls.

## Design principles
- Safety state is explicit: never silently convert a missing safety dependency into a normal low-risk state.
- One action, one owner: `CareTask` owns care intent and lifecycle; `Reminder` owns scheduling and delivery projection.
- Privacy is a product boundary: family views outcomes and necessary summaries, not unrestricted elder conversations.
- Human control remains available: users can correct, cancel, snooze, revoke, and escalate automated actions.
- Production truth over presentation: every visible status comes from persisted or explicitly ephemeral state with provenance.
- Progressive disclosure: elder and family screens show care meaning; technical details live in operator surfaces.
- Exception first: family and operator screens prioritize what requires action, not activity volume or engagement.
- One owner, one next action: every unresolved alert or missed task names who owns it, when it is due, and what happens next.
- Preserve elder agency: ask before sharing where possible, show what was shared, and make correction or revocation reachable.
- Tradeoffs: a slightly slower explicit confirmation is preferred over an incorrect care mutation; availability may degrade, but safety and audit claims must never degrade silently.

## Visual language
- Color: neutral backgrounds with semantic status tokens for safe, information, warning, critical, success, offline, and unknown. Critical red is reserved for actionable risk, not decoration.
- Typography: Chinese-first system fonts; elder body text starts at 18px with generous line height, family body text at 16px, and operator density may be lower only when contrast and zoom remain accessible.
- Spacing/layout rhythm: 4px base scale; major sections use 16–24px spacing; primary actions remain visually isolated from destructive actions.
- Shape/radius/elevation: 6–8px radius for controls and cards; borders and spacing establish hierarchy; shadows are reserved for overlays and active elevation.
- Motion: short and functional; no decorative streaming animation. Respect reduced-motion preferences and never rely on motion to convey risk.
- Imagery/iconography: use familiar Lucide-style symbols with text where interpretation matters. Product evidence uses real product/device states with date and environment labels.

## Components
- Existing components to reuse: `ChatWindow`, `MessageBubble`, `CareTaskClarifyCard`, `RiskAlertBanner`, `ToolStatusBadge`, and `TraceTimeline`, after moving them into role-appropriate surfaces.
- New/changed components:
  - `RoleShell`, `CareTaskCard`, `TaskConfirmation`, `DeliveryReceipt`, `AlertCaseCard`, `FamilySummary`, `DeviceStatus`, `ConsentScope`, and shared `EmptyState`, `LoadingState`, `ErrorState`.
  - Household onboarding checklist, verified-contact editor, care exception card, escalation owner control, next-action control, and policy-version badge.
  - `ChatWindow` removes runtime selection, TTFT, trace links, and tool-showcase prompts from elder/family mode.
  - `CareTaskClarifyCard` shows the exact affected task, accessible choices, disabled/submitting states, and a persisted confirmation result.
- Variants and states: normal, due soon, due, overdue, acknowledged, completed, snoozed, delivery pending, delivery failed, escalated, offline, unknown, and permission denied.
- Token/component ownership: semantic tokens live in `apps/web/app/globals.css` and Tailwind theme extension; components consume named tokens rather than raw palette classes.

## Accessibility
- Target standard: WCAG 2.2 AA for web surfaces, plus elder-specific readability and cognitive-load checks.
- Keyboard/focus behavior: all actions are reachable in logical order; focus is visible; dialogs trap and restore focus; no keyboard-only dead ends.
- Contrast/readability: text and status meet AA contrast; status is never conveyed by color alone; zoom to 200% preserves task completion flows.
- Screen-reader semantics: visible labels for inputs, descriptive names for icon buttons, live regions for streaming/status changes, structured headings, and explicit error association.
- Reduced motion and sensory considerations: honor `prefers-reduced-motion`; provide text equivalents for audio state; avoid rapid flashes and unexpected audio.
- Touch: interactive targets are at least 44x44 CSS pixels with separation sufficient for tremor and low dexterity.
- Elder surfaces use at least 18px body copy and 48px touch targets for primary actions.
- Voice is never the only channel: every spoken reminder and safety prompt has visible text or a physical/device acknowledgement alternative.

## Responsive behavior
- Supported breakpoints/devices: 360px mobile web through desktop operations consoles; elder voice device is a separate surface using the same domain contracts.
- Layout adaptations:
  - Elder: single-column actions, persistent high-priority help, safe-area-aware composer, no desktop sidebar dependency.
  - Family: bottom navigation or compact drawer on mobile; overview cards become ordered full-width sections.
  - Operators: dense tables may scroll horizontally, but severity, owner, and next action remain pinned and readable.
- Touch/hover differences: hover only supplements focus and pressed states; destructive controls require explicit confirmation and are not adjacent to routine completion.

## Interaction states
- Loading: use a stable skeleton or progress label that preserves layout and states what is loading.
- Empty: distinguish “nothing scheduled,” “no exceptions,” and “not authorized”; provide one relevant next action.
- Error: identify whether the failure is local, delivery, permission, dependency, or safety configuration; provide retry only when retry is safe.
- Success: confirm the domain result and next occurrence, not merely “request succeeded.”
- Disabled: explain the unmet prerequisite, such as missing consent, offline device, or unresolved ambiguity.
- Offline/slow network: queue only actions with idempotency and visible pending state; safety escalations show that delivery is unconfirmed and expose a human fallback path.
- Onboarding: identity pending, caregiver contact unverified, consent incomplete, device offline, notification channel unverified, and pilot ready are explicit states.
- Case handling: open, assigned, waiting for caregiver, waiting for elder, escalated, resolved, and closed-with-reason are explicit states.

## Content voice
- Tone: warm, direct, respectful, and non-judgmental; short sentences during stress.
- Terminology:
  - Elder/family: 陪伴、今日事项、提醒、已确认、需要关注、联系家人.
  - Operator only: Trace, TTFT, model route, webhook, policy version.
  - Say “可能存在风险，需要确认” instead of claiming diagnosis or certainty.
- Microcopy rules:
  - Repeat dates, times, medication/task names, recipients, and destructive consequences before confirmation.
  - State what the system did, what remains unconfirmed, and what the user can do next.
  - Do not say “已通知家属” until a provider accepted the message; distinguish queued, sent, delivered, read, and failed.
  - Only repeat or schedule a date/time that was present in the elder's own utterance or explicitly confirmed by them; model-generated timestamps are not user intent.
  - CareTask mutation confirmations use backend-owned deterministic copy. Do not append a second model-written success paragraph.

## Implementation constraints
- Framework/styling system: Next.js 14, React 18, TypeScript, Zustand, and Tailwind CSS 3. Extend existing patterns before adding a design-system dependency.
- Design-token constraints: introduce semantic CSS variables and Tailwind aliases incrementally; do not create a parallel component framework.
- Performance constraints: elder first meaningful response and task confirmation remain usable on mid-range mobile networks; operator diagnostics must not block the care path.
- Compatibility constraints: production role authorization is enforced server-side; client routing is presentation, not an access-control boundary.
- Public family product APIs expose `CareTask`; `Reminder` remains an internal scheduling and delivery projection. Legacy reminder routes may remain for compatibility but do not drive new UI.
- `sandbox` or `unconfigured` notification providers cannot satisfy pilot readiness or render an alert as delivered.
- AI-generated summaries require provenance, purpose, consent scope, and a correction path. Raw transcript access is a separate permission and is off by default.
- Test/screenshot expectations:
  - Add component or end-to-end tests for role routing, task clarification, task mutation, alert receipts, permission denial, and offline states.
  - Verify mobile 360x800, tablet 768x1024, and desktop 1440x900.
  - Product evidence includes commit SHA, environment, account role, timestamp, and backend trace or receipt identifiers.
  - `docs/evidence` mock assets remain documentation-only and cannot be labeled as production screenshots.

## Open questions
- [ ] Founders: choose the first deployment jurisdiction and pilot setting; this determines legal, hosting, retention, and incident obligations.
- [ ] Product/safety: approve the escalation matrix for scam, emotional crisis, health emergency, missed medication, device outage, and failed contact.
- [ ] Product: decide whether the first paid pilot is direct-to-family or distributed by one home-care partner; do not build both onboarding models in the same cycle.
- [ ] Product: validate the minimum family summary through interviews with at least five elders and five caregivers before adding longitudinal insights.
- [ ] Hardware: choose device identity, secure boot, signed update, provisioning, and field-recovery approach before a multi-home pilot.
- [ ] Operations: define staffed escalation hours and the explicit behavior outside those hours.
- [ ] Clinical/legal advisor: approve health-language boundaries and evidence requirements before making healthcare efficacy claims.
