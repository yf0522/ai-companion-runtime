# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-07-11
- Primary product surfaces: elder companion, elder daily care and help, family exception coordination, household readiness, operator cases, and runtime traces.
- Evidence reviewed: `README.md`, `docs/product-roadmap-2026-h2.md`, `docs/superpowers/specs/2026-06-15-elder-companion-pivot-design.md`, `apps/web/app`, `apps/web/components`, `apps/web/stores`, `apps/web/lib`, `apps/web/e2e/product-surfaces.spec.ts`, and screenshots of the merged PR #45 UI at 1440x1000 and 390x844.
- Replacement decision: preserve PR #45's product information architecture, API/WebSocket/auth/RBAC contracts, and truthful state handling. Replace its graphite/electric-cyan visual layer, decorative signal field, repeated English badges, generic shared dashboard shell, and border-heavy page composition.

## Brand
- Name in product: Companion.
- Direction: **Quiet Care** — a calm, high-trust household care product, not an AI runtime console.
- Personality: warm, lucid, respectful, quietly capable, and composed under stress.
- Trust signals: a clear next action, truthful delivery state, named human ownership, visible uncertainty, and an always-available human fallback.
- Avoid: internal-tool chrome on elder/family surfaces, electric or neon accents, cybersecurity/observability aesthetics, decorative network lines or particles, English eyebrow labels, badge-shaped section headings, generic AI gradients/orbs, mascots, surveillance framing, and medical-authority claims.

## Product goals
- Give an elder one obvious place to speak, confirm, and ask a person for help without learning system terminology.
- Let a family caregiver answer “does anything need attention now?” in under 30 seconds.
- Put unresolved exceptions and their next actions before metrics, inventory, or explanatory copy.
- Give operators a dense, evidence-oriented queue without making consumer surfaces inherit operator language.
- Preserve privacy boundaries: family sees agreed outcomes and exceptions; operators see authorized evidence; elder conversation is not a family feed.
- Success signals:
  - The primary action is visible without scrolling at 390x844.
  - A family user can identify the highest-priority exception and its next action in one scan.
  - Elder pages contain no implementation terms such as Harness, Trace, runtime, outbox, or permission isolation.
  - Decorative labels can be removed without losing comprehension because hierarchy comes from layout and typography.

## Product non-goals
- Diagnose disease, prescribe treatment, replace emergency services, guarantee harm prevention, or autonomously move money.
- Claim phone/message interception, production notification delivery, or hardware closure without corresponding evidence.
- Show private transcripts or inferred emotional history to family by default.
- Make the product feel premium by adding gradients, glass effects, excessive motion, or ornamental illustration.

## Personas and jobs
- Elder:
  - Jobs: speak naturally, understand what happens next, confirm a care action, identify possible fraud, and contact a trusted person.
  - Context: variable vision, dexterity, device familiarity, attention, and network quality; often mobile or tablet; stress may be elevated.
- Family caregiver:
  - Jobs: see whether attention is needed, know what was delivered or acknowledged, manage agreed tasks, and maintain the care circle.
  - Context: short, interruption-heavy checks on a phone; needs confidence without transcript surveillance.
- Operator:
  - Jobs: triage cases, establish ownership, inspect policy/model/tool/delivery evidence, record activity, and resolve with a reason.
  - Context: desktop-first, repeated scanning, higher information density, and domain terminology is acceptable.

## Information architecture
- Elder:
  - `陪伴` is a conversation and next-action surface, not a dashboard.
  - `今日事项` is a focused confirmation queue.
  - `帮助` keeps trusted-person and emergency guidance continuously reachable.
  - Navigation is limited to these three destinations and does not use a desktop admin sidebar.
- Family:
  - `概览` opens on the highest-priority unresolved exception or a clear all-good state.
  - Tasks, alerts, people, contacts, readiness, and summary remain supporting workspaces.
  - Metrics and privacy explanations are secondary; they never precede the current exception.
- Operator:
  - Care cases are the primary command queue.
  - Readiness and traces are supporting evidence workspaces.
  - Desktop navigation may retain a compact operational sidebar.
- Content hierarchy:
  1. Current state in plain language.
  2. One accountable next action.
  3. Essential evidence or timing.
  4. Supporting totals, history, and system detail.

## Design principles
1. **Care before capability.** Show what the person needs now, not what the system can technically do.
2. **One page, one opening statement.** Do not stack a shell title, hero, metric strip, and repeated section intros.
3. **Exceptions before summaries.** A real unresolved exception outranks metrics and navigation shortcuts.
4. **Warmth comes from restraint.** Fewer elements, careful type, purposeful whitespace, and honest language create trust.
5. **Different roles deserve different density.** Elder, family, and operator surfaces share brand tokens, not an identical shell.
6. **State earns motion and color.** Animation and semantic color appear only when a real state changes.
7. **Privacy is enforced, not advertised repeatedly.** Explain it where a sharing decision occurs; do not use “permission isolation” as ambient decoration.

## Visual language
- Color:
  - Canvas: warm ivory `#F4F1EA`.
  - Primary surface: paper white `#FCFBF7`.
  - Ink: pine-black `#1F2925`.
  - Muted text: stone-sage `#65706A`.
  - Brand/action: mature sage `#416F61` with dark state `#31574C`.
  - Brand soft: `#DDE8E1`.
  - Critical: muted brick `#A64D40`; critical soft `#F6E5E0`.
  - Warning: ochre `#9A672D`; warning soft `#F5EBD9`.
  - Success: leaf `#3E7056`; success soft `#E2EEE7`.
  - Operator surfaces may use cooler neutral grays but retain the same semantic colors.
- Typography:
  - Chinese-first system stack with PingFang SC / Noto Sans SC and restrained Latin fallbacks.
  - Elder display: 40–52px desktop, 30–36px mobile, never used for operational metadata.
  - Page title: 28–32px; section title: 20–24px; body: 16–18px; supporting text: 13–14px.
  - Use four hierarchy levels at most on one screen. Avoid all-caps English decoration.
- Spacing/layout rhythm:
  - Base scale: 4, 8, 12, 16, 24, 32, 48, 64.
  - Family reading width: 960–1080px. Operator queue may use the full available width.
  - Whitespace separates decisions; repeated 1px rules do not substitute for grouping.
- Shape/radius/elevation:
  - Controls: 10px radius; primary consumer surfaces: 14–16px; status chips only may be pill-shaped.
  - Use borders only when they clarify interaction or state.
  - One soft active-plane shadow is allowed; inactive content should sit naturally on the canvas.
- Motion:
  - Listening, connecting, streaming, successful handoff, and escalation may animate.
  - Idle screens, login, and static empty states do not contain drifting lines, particles, or pulsing decoration.
  - Respect `prefers-reduced-motion`.
- Imagery/iconography:
  - No decorative network marks or generic AI glyphs.
  - Icons are 18–22px, used only when they improve recognition.
  - The wordmark may stand alone; a brand mark must not resemble infrastructure or security tooling.

## Components
- Existing components to reuse for behavior/accessibility:
  - Astryx `Theme`, `LinkProvider`, buttons, inputs, chat composition, empty/error/loading primitives, and operator navigation where useful.
  - Existing API clients, stores, message renderer, care-task clarification, and truthful status mappings.
- New or substantially changed presentation components:
  - `RoleShell`: separate elder, family, and operator composition instead of one shared dashboard frame.
  - `PageIntro`: replace badge-led hero treatment with a compact page header; no decorative kicker.
  - `AttentionCard`: semantic risk surface with a direct next action and delivery evidence.
  - `CareTaskCard`: compact row on family/operator surfaces; legible confirmation surface on elder pages.
  - `CompanionSignal`: quiet text/state treatment driven by the real WebSocket state.
- Variants and states:
  - Severity changes border/background/icon treatment, not only a small badge.
  - Delivered, acknowledged, unresolved, and failed remain visually distinct.
  - Disabled controls retain legibility and explain recovery or fallback.
- Token/component ownership:
  - Product colors, typography, spacing, radii, and elevation live in `apps/web/app/globals.css` CSS variables.
  - Astryx supplies behavior and accessibility; product CSS owns the consumer visual language.
  - No new design-system dependency is introduced for this refactor.

## Accessibility
- Target: WCAG 2.2 AA for primary flows.
- All primary actions have at least 44px touch targets.
- Focus is visible and not communicated by color alone.
- Live regions announce connection, streaming, delivery, and error states without repeating static decoration.
- Body text remains at least 16px on elder surfaces; supporting text does not carry the only instance of critical information.
- Reduced motion removes all nonessential animation.

## Responsive behavior
- Release viewports: 390x844, 768x1024, and 1440x1000.
- Elder:
  - No desktop admin sidebar; three destinations remain reachable through a quiet header/bottom navigation pattern.
  - Composer and human-help fallback remain visible without hiding the current state.
- Family:
  - The current exception and its action appear before metrics at 390x844.
  - Bottom navigation contains only primary destinations; the complete route set remains available through the mobile menu.
- Operator:
  - Desktop retains a compact sidebar and dense queue.
  - Mobile stacks evidence cells and keeps the case action full width.
- Horizontal scrolling is reserved for operator evidence, never for primary family navigation.

## Interaction states
- Loading: preserve layout and name the content being synchronized.
- Empty: state the outcome first; do not fill the screen with generic illustration or capability marketing.
- Error: explain what remains safe, what failed, and the one available recovery action.
- Success: confirm the completed outcome and whether another human or system acknowledgement is still pending.
- Disabled: retain readable content and state why the action is unavailable.
- Offline/slow network: expose human fallback immediately; never imply delivery or completion.
- Risk: interrupt normal hierarchy with plain-language guidance and the safest next action.

## Content voice
- Tone: direct, warm, specific, and calm; never promotional inside an authenticated workflow.
- Elder/family terminology: care task, today, family, contact, needs attention, delivered, confirmed, and help.
- Operator-only terminology: Trace, outbox, runtime, policy decision, delivery attempt, and evidence handle.
- Microcopy rules:
  - No decorative English labels on Chinese surfaces.
  - Avoid “AI intelligence,” “runtime,” and capability lists when a user outcome can be stated.
  - Prefer “现在需要你确认一件事” over “1 件异常.”
  - Prefer “已送达家人，尚未确认处理” over a bare “delivered” badge.
  - One sentence should not explain both product philosophy and the current action.

## Implementation constraints
- Framework/styling: Next.js 15.5, React 19, TypeScript, Zustand, Tailwind utilities, existing Astryx packages, and Lucide icons.
- No new dependencies for this visual refactor.
- Astryx reset/core/theme styles load before product CSS; product tokens and scoped role styles intentionally override visual defaults.
- Preserve API, WebSocket, auth, RBAC, persistence, privacy, safety, and exact care-task clarification contracts.
- Preserve public `CareTask` language and truthful notification/provider states.
- Performance: no large raster background, animation library, or decorative WebGL/canvas layer.
- Test/screenshot expectations:
  - Typecheck, unit tests, production build, Astryx doctor, and Playwright role tests pass.
  - Visual references and generated screenshots are stored under `.omx/artifacts/visual-ralph/quiet-care/`.
  - Required screenshot states: login, elder companion, family overview with one high-risk alert, operator queue with one critical case; desktop 1440x1000 and mobile 390x844 where applicable.
  - Family mobile verification asserts that the actionable exception is visible within the first viewport, not merely attached to the DOM.

## Open questions
- [ ] Validate Quiet Care with at least five elders and five family caregivers before treating it as a production brand system.
- [ ] Decide whether first distribution is direct-to-family or through one home-care partner; this affects onboarding voice and trust proof.
- [ ] Approve the escalation matrix and staffed escalation hours before implying always-available human response.
- [ ] Commission or intentionally reject a bespoke Companion mark after the product direction is validated; use the wordmark alone until then.
- [ ] Validate the minimum family summary with elders and caregivers before adding longitudinal inference.
