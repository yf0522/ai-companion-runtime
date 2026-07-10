# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-07-11
- Primary product surfaces: elder companion, elder daily care, family exception coordination, household readiness, operator cases, runtime traces.
- Evidence reviewed: `README.md`, `apps/web/app`, `apps/web/components`, `apps/web/stores`, `apps/web/lib`, `apps/api/app/api`, `apps/api/app/runtime`, `docs/product-roadmap-2026-h2.md`, `docs/device-test.md`, and `apps/web/e2e/product-surfaces.spec.ts`.
- Replacement decision: the previous Calm Intelligence UI and its dashboard/card visual language are retired. API, WebSocket, persistence, role routing, privacy, and safety contracts remain; visual structure and interaction composition do not.

## Product thesis
- Category: a family-funded home-care coordination system delivered through a real-time elder companion.
- Core product state: conversation is the natural-language control surface; care tasks, safety decisions, delivery receipts, household consent, operator cases, and traces are the accountable state.
- Product promise: help an elder complete agreed daily actions, surface verified exceptions to authorized family members, and give operators enough evidence to intervene without exposing private conversation by default.
- Production rule: no investor-only behavior, mock evidence labeled as live, or UI claims that bypass normal authorization, persistence, delivery, or audit paths.

## Brand
- Name in product: Companion.
- Personality: present, lucid, humane, technically confident, and restrained under stress.
- Trust signals: live connection state, explicit execution state, named human ownership, delivery receipts, visible uncertainty, and trace/evidence handles.
- Avoid: traditional admin-template chrome, generic chatbot bubbles, neon gradients, decorative orbs, anthropomorphic mascots, medical-authority claims, surveillance framing, and dense technical language on elder/family surfaces.

## Product goals
- Give elders one obvious place to speak, confirm, and ask for help.
- Put unresolved exceptions before routine work for family users.
- Turn operator work into a severity-, owner-, and evidence-driven queue.
- Make AI activity legible through real runtime signals and tool state rather than decorative AI styling.
- Preserve privacy boundaries: family sees outcomes and exceptions; operator sees authorized evidence; elder conversation is not a family feed.

## Non-goals
- Diagnose disease, prescribe treatment, replace emergency services, guarantee harm prevention, or autonomously move money.
- Claim phone/message interception without a shipped integration.
- Show private transcripts or inferred emotional history to family by default.
- Make sandbox notification providers or in-memory bindings look pilot-ready.

## Personas and jobs
- Elder: speak naturally, understand what happens next, confirm a care action, identify possible fraud, and contact a human.
- Family caregiver: see what needs attention, know whether notification delivery actually occurred, manage agreed care tasks, and maintain the care circle.
- Operator: triage cases, establish ownership, inspect policy/model/tool/delivery evidence, record activity, and resolve with a reason.

## Information architecture
- Elder mode: `陪伴` is the full-height primary workspace; `今日事项` is a focused confirmation queue; `帮助` is an emergency and human-handoff surface.
- Family mode: `概览` is an exception stream; tasks, alerts, people, contacts, readiness, and summary are supporting workspaces.
- Operator mode: care cases are the primary command queue; readiness and traces are evidence workspaces.
- Navigation adapts by role. Elder navigation is sparse and high-legibility. Family navigation is calm and outcome-led. Operator navigation is compact and evidence-led.

## Design principles
1. **Presence before chrome.** The elder experience opens on the companion and the next action, not a dashboard header.
2. **Exceptions before inventory.** Family and operator surfaces rank unresolved risk above counts and routine lists.
3. **AI is a live system state.** Connection, analysis, tool calls, streaming, memory/runtime selection, and delivery state create the AI character.
4. **One accountable action per region.** High-stakes surfaces expose a clear next action and show what remains unconfirmed.
5. **Different roles deserve different density.** Do not reuse a generic page template across elder, family, and operator modes.
6. **Motion explains state.** Animation indicates listening, connecting, reasoning, streaming, escalation, or successful handoff; it never decorates idle screens.

## Visual language
- Foundation: Astryx neutral theme and components, with a product-specific shell and signal system.
- Color: graphite and porcelain for structure; electric cyan/teal for live intelligence; green for verified completion; amber for uncertainty; coral/red for human escalation and critical risk. Purple is not a dominant brand color.
- Typography: system sans with Chinese-first legibility; large but contained elder copy; compact tabular metrics and monospace evidence only in operator mode.
- Shape: Astryx component radii; page-level surfaces max 8px unless an Astryx control requires its native radius. No nested cards.
- Elevation: sparse. Use border, surface contrast, and one active-plane shadow instead of floating card stacks.
- Motion: signal bars, scanning rails, message entrance, streaming pulse, connection transitions, and status confirmation. Respect `prefers-reduced-motion`.
- Backgrounds: solid surfaces plus code-native line/dot signal fields. No gradient, orb, bokeh, or stock-illustration backgrounds.

## Component system
- Required Astryx primitives: `Theme`, `LinkProvider`, `AppShell`, `SideNav`, `ChatLayout`, `ChatComposer`, `ChatMessage*`, `ChatToolCalls`, `Button`, `Badge`, `Card`, `Text`, `Heading`, `Avatar`, `Spinner`, and layout stacks.
- Shared product components:
  - `ProductProvider`: Astryx theme and Next.js routing bridge.
  - `RoleShell`: authorization hydration, role-specific navigation, mobile navigation, page framing, and runtime status rail.
  - `SignalField`: stateful ambient line animation, never decorative-only.
  - `CompanionSignal`: real WebSocket state represented as motion and text.
  - `PageIntro`: consistent page identity without marketing hero treatment.
  - `StatusBanner`, `LoadingState`, `EmptyState`, `ErrorState`: Astryx-backed system states.
  - `CareTaskCard`, `AlertCaseCard`: accountable domain rows, not generic cards.
- Chat composition: `ChatLayout` owns scrolling and the frosted composer dock; user messages use filled bubbles; assistant messages use ghost bubbles; tool calls use `ChatToolCalls`; risk intervention precedes assistant prose.

## Interaction states
- Connected: signal motion is calm and continuous.
- Connecting/reconnecting: motion becomes stepped and status copy names recovery.
- Streaming: assistant state and stop control are visible; duplicate sends remain blocked.
- Tool running/result: tool name, state, and duration/evidence are exposed at the appropriate role level.
- Offline: no action is presented as completed or delivered; human fallback is visible.
- Risk: critical instruction interrupts normal hierarchy; ordinary tool actions stop where policy requires.
- Loading/empty/error: stable layout, specific cause, and only safe retry actions.

## Responsive and accessibility
- Release viewports: 390x844, 768x1024, and 1440x1000.
- All primary actions meet 44px touch targets even when underlying Astryx controls are denser.
- Mobile navigation keeps every role route reachable without relying on hover.
- Focus is visible, live regions are used for connection/stream states, and motion reduction removes nonessential animation.
- Elder copy does not use operator terminology. Operator evidence remains selectable and horizontally scrollable when necessary.

## Implementation constraints
- Frontend platform: Next.js 15.5, React 19, TypeScript, Zustand, Tailwind utilities, Astryx core/theme-neutral, and Lucide icons.
- Astryx reset, core CSS, and neutral theme CSS load before application CSS.
- Existing API client, WebSocket store, role routes, server RBAC, persistence formats, and exact care-task clarification command remain compatible.
- Public family UI uses `CareTask`; legacy reminder routes remain redirects only.
- Sandbox or unconfigured notification providers cannot render as delivered or pilot-ready.
- New features include happy-path plus boundary/failure tests; UI changes retain existing role/permission/ordering tests.

## Verification
- `astryx doctor`, TypeScript, unit tests, Next production build, and Playwright role matrix must pass.
- Real WebSocket chat is tested against the local API, including runtime hydration and reconnect behavior.
- Screenshots are reviewed at mobile, tablet, and desktop sizes for overlap, clipping, empty canvases, and broken motion.
- Completion requires no known console errors and no unresolved visual regressions on the three primary role entry pages.

## Open questions
- Choose the first pilot jurisdiction and staffed escalation hours.
- Approve the escalation matrix for scam, emotional crisis, health emergency, missed medication, device outage, and failed contact.
- Decide whether first distribution is direct-to-family or through one home-care partner.
- Validate the minimum family summary with elders and caregivers before adding longitudinal inference.
