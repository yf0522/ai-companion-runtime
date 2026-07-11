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
