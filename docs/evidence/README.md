# Demo Evidence

This directory stores public investor/demo assets that should remain accessible from the GitHub repository.

## Disclaimer

These images are **Mock UI · scenario demo** materials. They illustrate intended user flows and product direction. They are not production screenshots and should not be presented as shipped App UI.

Use them to explain the product thesis, interaction model, and value loop. Do not use them as evidence that a mobile App, hardware shell, or phone-intercept capability is already production-live end to end.

## Evidence Index

1. [01-voice-clone-trust.png](./01-voice-clone-trust.png)
2. [02-daily-memory-summary.png](./02-daily-memory-summary.png)
3. [03-hardware-phone-intercept.png](./03-hardware-phone-intercept.png)
4. [04-labor-saved-overview.png](./04-labor-saved-overview.png)

### Related diligence artifacts (non-Mock)

| Artifact | Meaning |
|---|---|
| `device-protocol-expected-sequence-*.txt` | Annotated expected protocol sequence — **not** a live ESP32 serial capture |
| `device-serial-log-*.txt` (if present) | Only treat as live board evidence if the file header says so |
| `demo-run-*.md` | Smoke checklist output; dry-run ≠ live API proof |
| `latency-baseline.json` | Mocked AgentHarness p50/p95 latency baseline for CI regression checks |

## Latency baseline (CI)

`latency-baseline.json` stores p50/p95 timings from `scripts/latency_bench.py` using **mocked** model adapters (no API keys). GitHub Actions workflow `.github/workflows/latency.yml` fails PRs when p95 regresses more than **20%** vs this file, or exceeds absolute ceilings.

Update after intentional harness changes:

```bash
cd <repo-root>
python -m pip install -e "apps/api[dev]"
python scripts/latency_bench.py --iterations 5 --update-baseline docs/evidence/latency-baseline.json
cd apps/api && pytest -q tests/test_latency_bench.py
git add docs/evidence/latency-baseline.json
```

The software runtime loop is verified for chat. Device-routed transcripts and firmware protocol alignment land as separate workstreams. Hardware execution evidence remains separate from Mock UI.

## 01. Voice profile and trust reminder

![Voice profile and trust reminder demo](./01-voice-clone-trust.png)

What the image shows:
- Left side is the child-facing mobile flow: the child records a short voice sample and creates a reusable voice profile.
- Right side is the elder-facing device or large-text interface: the reminder is delivered in a more familiar, trusted voice and with a single large confirmation action.
- The bottom banner makes the intended value claim explicit: train once, improve daily compliance, reduce repeated reminder calls from children.

Product point being communicated:
- The core idea is not generic voice cloning. The point is trust transfer: reminders feel more personal when they sound like family.
- The child does configuration once; the elder receives a lower-friction, higher-acceptance reminder experience.
- The elder-side interface is intentionally simple: one clear message, one large action, minimal cognitive load.

Why this matters in the eldercare narrative:
- Medication adherence is a high-frequency, high-trust problem.
- The image frames the system as a care runtime that turns family input into repeated daily assistance, not as a novelty chat UI.
- It also shows the dual-end model clearly: child configures on phone, elder consumes on dedicated surface.

Boundary / non-claim:
- This image should be described as a scenario concept for voice-profile-driven reminders.
- It should not be described as proof that production voice cloning, device playback, or end-to-end on-device reminder execution is already shipped.

## 02. Daily memory and family summary

![Daily memory and family summary demo](./02-daily-memory-summary.png)

What the image shows:
- Upper-left scene: the elder casually speaks about the day; the system writes memory and updates daily state.
- Lower-left scene: the child asks a simple question such as “妈今天怎么样？” and receives a structured summary instead of making another checking call.
- Right side: a family-facing weekly summary screen aggregates medication completion, emotional events, suspicious-call intercept count, and repeated physical discomfort signals.

Product point being communicated:
- This image is selling persistent memory plus family summarization, not one-turn chat.
- The elder speaks naturally in daily life; the system turns unstructured speech into family-readable status.
- The child’s benefit is operational compression: one summary view replaces repeated ad hoc check-ins.

Why this matters in the eldercare narrative:
- Families often do not need a full transcript; they need a concise, decision-ready status summary.
- The image positions long-term memory as a care coordination primitive: medication, mood, symptoms, and social activity become structured follow-up signals.
- It connects directly to the runtime thesis: memory write, summarization, and downstream family visibility are reusable infrastructure.

What is strong in the visual:
- The split timeline “elder morning / child evening” makes the asynchronous care loop easy to understand.
- The weekly summary screen implies trend detection rather than isolated events.
- The repeated leg-soreness cue suggests the path from daily observation to actionable health escalation.

Boundary / non-claim:
- This should be framed as a mock summary experience powered by memory and risk/event aggregation concepts.
- Do not present the exact mobile UI, weekly card layout, or every listed metric as already productized unless the backend path is verified.

## 03. Hardware-assisted phone intercept

![Hardware-assisted phone intercept demo](./03-hardware-phone-intercept.png)

What the image shows:
- An elder is receiving a suspicious call on a phone while a companion device is linked locally.
- The device is shown as intervening: muting the phone ring path or shielding the call surface, then presenting a simpler elder-facing choice.
- The right-side flow explains the concept architecture: companion device initiates intervention, phone is affected, elder only decides whether to hang up or continue.

Product point being communicated:
- This image is making the boldest claim in the set: hardware can intervene upstream of the elder’s phone interaction rather than only warning after the fact.
- The focus is fraud prevention under low digital literacy conditions.
- The elder experience is simplified from “interpret a suspicious incoming call” to “choose between two clear outcomes.”

Why this matters in the eldercare narrative:
- Anti-fraud is a high-trust, high-value family pain point with direct willingness to pay.
- The image moves the product from passive assistant to active safety system.
- It differentiates the concept from a normal mobile app by emphasizing device-originated intervention.

What the right-side explanation is trying to prove:
- Intervention does not rely on the elder voluntarily opening an App.
- The effect happens at the call moment, near the phone interaction surface.
- The care device acts as a protective control plane for the elder, not just a notification endpoint.

Boundary / non-claim:
- This is a concept/mock for hardware-assisted intercept behavior.
- It should not be described as evidence that full phone OS integration, call interception permissions, or transfer-blocking is already shipping across production devices.

## 04. Labor saved overview

![Labor saved overview demo](./04-labor-saved-overview.png)

What the image shows:
- A one-page summary of three pillars: voice profile, long-term memory, and hardware-assisted phone intervention.
- Each column pairs an elder-facing interaction with a child-facing outcome.
- The bottom row translates those pillars into practical family value: fewer medication reminder calls, less repeated checking-in, less after-the-fact rights protection or alarm handling.

Product point being communicated:
- This is the highest-level business framing image in the set.
- It turns multiple product features into a single promise: elders can do small daily actions, and children carry less coordination burden.
- The selected tabs at the top show the intended platform story: these are not isolated demos, but pieces of one coherent system.

Why this matters in the investor narrative:
- The image is not about UI polish. It is about labor substitution and burden reduction.
- It reframes eldercare AI from “conversation” to “family operations compression.”
- The value proposition is clearer to a buyer when expressed as reduced follow-up calls, reduced repeated questioning, and reduced damage after scams.

How to talk about it:
- Use this image as the summary slide after showing one or two specific scenarios.
- Position the first two pillars as nearer-term software/runtime surfaces and the phone-intercept pillar as the more differentiated hardware direction.
- Tie it back to the runtime architecture: memory, risk classification, reminders, family visibility, and traceability.

Boundary / non-claim:
- This image is a narrative overview, not an implementation status page.
- Any presenter should keep the “Mock UI · scenario demo” qualifier visible in nearby context.
