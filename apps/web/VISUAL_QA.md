# Quiet Care visual QA

`DESIGN.md` defines the product contract. The approved Visual Ralph reference and generated screenshots live in the ignored runtime workspace at `.omx/artifacts/visual-ralph/quiet-care/`.

## Reference state

- Family overview with one unresolved high-risk scam alert.
- One scheduled care task: `晚间降压药`.
- Desktop viewport: 1440x1000.
- Mobile viewport: 390x844.
- Tablet release viewport: 768x1024.
- Authentication and API data are seeded locally; no production data is used.

## Reproduce screenshots

From `apps/web`:

```bash
npm run build
npm run dev -- --hostname 127.0.0.1 --port 3017
PLAYWRIGHT_BASE_URL=http://127.0.0.1:3017 npm run capture:quiet-care
```

Do not run `next build` while the development server is active because both processes write `.next`. This repository uses `output: standalone`; `next start` is not its supported production runner.

Outputs:

- `.omx/artifacts/visual-ralph/quiet-care/actual-family-desktop.png`
- `.omx/artifacts/visual-ralph/quiet-care/actual-family-mobile.png`
- `.omx/artifacts/visual-ralph/quiet-care/actual-login-desktop.png`
- `.omx/artifacts/visual-ralph/quiet-care/actual-elder-desktop.png`
- `.omx/artifacts/visual-ralph/quiet-care/actual-elder-tablet.png`
- `.omx/artifacts/visual-ralph/quiet-care/actual-family-alerts-mobile.png`
- `.omx/artifacts/visual-ralph/quiet-care/actual-operator-desktop.png`

## Acceptance

- Visual Ralph verdict score is at least 90 against the approved reference.
- The family mobile opening statement, alert title/state, and `查看并处理` action fit inside the first 390x844 viewport.
- Family alert history keeps delivery and acknowledgement badges visible at 390px.
- Elder primary navigation stays reachable without covering the composer at 768x1024.
- Four primary family destinations fit without horizontal scrolling; all routes remain available from the header menu.
- Pixel diff is secondary diagnostic evidence only. Differences caused by unavailable portrait, household identity, or longitudinal health data must not be closed by fabricating product state.

---

# Pi-only tools visual QA (Phase 4)

Frozen companion flows only — adjust chips/copy, not a layout redesign. Artifacts: `.omx/artifacts/visual-ralph/pi-only-tools/`.

## Frozen flows

1. **memory** — note + recall chip/copy showing `memory`
2. **caretask** — list/create chip/copy showing `caretask`
3. **utility** — weather/calc action chip/copy showing `utility`

Route: `/elder/companion` ( `/chat` redirects there ). Runtime picker must be absent (Pi-only).

## Reproduce screenshots

From `apps/web`:

```bash
npm run build
npm run dev -- --hostname 127.0.0.1 --port 3018
PLAYWRIGHT_BASE_URL=http://127.0.0.1:3018 npm run capture:pi-only-tools
```

Capture seeds localStorage chat messages with tool chips and aborts WebSocket so the stack API is optional for UI evidence.

Outputs:

- `.omx/artifacts/visual-ralph/pi-only-tools/actual-memory-note-recall.png`
- `.omx/artifacts/visual-ralph/pi-only-tools/actual-caretask-list-create.png`
- `.omx/artifacts/visual-ralph/pi-only-tools/actual-utility-action.png`
- matching `reference-*.png` baselines (first capture copies actual → reference)
- `capture-manifest.json`
- `verdict-*.json` Visual Ralph scores (target ≥90)

## Acceptance

- Chip labels clearly show `memory` / `caretask` / `utility` (not only “照护动作”).
- No Harness / 标准模式 / 实验模式 runtime escape on companion.
- Visual Ralph verdict score ≥90 per frozen flow against its reference.
- Pixel diff is secondary diagnostic evidence only.
