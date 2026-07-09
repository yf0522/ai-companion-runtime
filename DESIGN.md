# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-07-10
- Primary product surfaces: elder companion, family care dashboard, device experience, care operations, operator observability.
- Evidence reviewed: `README.md`; `apps/web/app`; `apps/web/components`; `apps/web/stores`; `apps/api/app/api`; `apps/api/app/runtime`; `apps/api/app/db/models.py`; `firmware`; `docs/device-test.md`; `docs/investor-demo.md`; `docs/superpowers/specs/2026-06-15-elder-companion-pivot-design.md`.
- Product rule: the investor walkthrough uses the same authenticated product and pilot environment as normal users. There is no separate investor-only product path, fake data flow, or UI that claims unshipped capability.

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
- Non-goals:
  - Diagnose disease, prescribe treatment, replace emergency services, or guarantee prevention of harm.
  - Intercept phone calls or messages at the operating-system level unless a separately shipped integration proves that capability.
  - Use cloned family voices without explicit consent, revocation, provenance, and abuse controls.
  - Build a presentation-only mode that bypasses production authorization, persistence, delivery, or audit paths.
- Success signals:
  - Care tasks are created, clarified, delivered, acknowledged, snoozed, completed, and escalated without silent state loss.
  - Family alerts show recipient, channel, attempt, receipt, and final status.
  - Critical safety configuration failures prevent unsafe service startup or produce an explicit unavailable state.
  - Elder and family workflows are usable on a phone without operator terminology.

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
  - Elder: companion, today, help.
  - Family: overview, care tasks, alerts, summaries, people and permissions.
  - Care operations: alert queue, elder/device status, case timeline, contact attempts.
  - Reliability/safety operations: traces, service health, policy versions, model/tool delivery diagnostics.
- Core routes/screens:
  - `/elder/companion`: production conversation and task interaction.
  - `/elder/today`: current tasks, due status, and simple completion history.
  - `/family/overview`: exceptions, next tasks, recent acknowledgements, and device status.
  - `/family/tasks`: create and manage care tasks; `CareTask` is the business entity and `Reminder` is its scheduling projection.
  - `/family/alerts`: risk events, notification attempts, receipts, and resolution.
  - `/family/summary`: consented, minimum-necessary care summary; never a private chat transcript by default.
  - `/ops/care`: operational cases and manual escalation.
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

## Implementation constraints
- Framework/styling system: Next.js 14, React 18, TypeScript, Zustand, and Tailwind CSS 3. Extend existing patterns before adding a design-system dependency.
- Design-token constraints: introduce semantic CSS variables and Tailwind aliases incrementally; do not create a parallel component framework.
- Performance constraints: elder first meaningful response and task confirmation remain usable on mid-range mobile networks; operator diagnostics must not block the care path.
- Compatibility constraints: production role authorization is enforced server-side; client routing is presentation, not an access-control boundary.
- Test/screenshot expectations:
  - Add component or end-to-end tests for role routing, task clarification, task mutation, alert receipts, permission denial, and offline states.
  - Verify mobile 360x800, tablet 768x1024, and desktop 1440x900.
  - Product evidence includes commit SHA, environment, account role, timestamp, and backend trace or receipt identifiers.
  - `docs/evidence` mock assets remain documentation-only and cannot be labeled as production screenshots.

## Open questions
- [ ] Founders: choose the first deployment jurisdiction and pilot setting; this determines legal, hosting, retention, and incident obligations.
- [ ] Product/safety: define which risk categories require automatic contact, user confirmation, operator review, or emergency-service guidance.
- [ ] Product: define family summary scope and elder consent/revocation experience before exposing longitudinal insights.
- [ ] Hardware: choose device identity, secure boot, signed update, provisioning, and field-recovery approach before a multi-home pilot.
- [ ] Operations: define staffed escalation hours and the explicit behavior outside those hours.
- [ ] Clinical/legal advisor: approve health-language boundaries and evidence requirements before making healthcare efficacy claims.
