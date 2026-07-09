# Investor Demo Script

Target length: 3 minutes

This is an **eldercare risk-gated runtime demo**, not an entertainment chatbot demo.
The goal is to prove: companionship + memory + safety interception + family handoff + traceability in one interaction loop.

## Scenario visuals

For investor-facing scenario mockups (voice trust, daily memory summary, hardware phone intercept, labor-saved overview), see [`docs/evidence/`](./evidence/README.md). These are **Mock UI · scenario demo** assets, not production screenshots.

## Setup

- Backend API running: `http://localhost:8000`
- Web console running: `http://localhost:3000`
- Trace view open, waiting for a new trace ID
- Device or device-simulated WS client connected
- Pre-configured elderly user profile in memory:
  - 慢病用药：晚上 20:00 吃降压药
  - 近期就诊提醒/作息
  - 家属联系人已开启
- Prepared expected categories:
  - `health_emergency`, `scam_alert`, `emotional_low`

## 0:00-0:18 Opening

> “AI Companion Runtime is not just conversational AI.
> It is a reusable runtime for eldercare: realtime dialogue, memory-driven reminders, risk-gated routing, tool execution, and trace observability.
> Today we show the complete safety loop.”

Show:
- `/ws/device/realtime` connect result (or `/ws/chat` with token)
- Trace panel empty state

## 0:18-0:48 Memory + companionship + reminder

User says:

```text
我今天有点头晕，药是不是还没吃？
```

Expected behavior:

- Analyzer marks intent and emotion, then memory recall supplements context.
- The runtime responds as eldercare companion with a warm reminder style, not a generic one-shot answer.
- It confirms whether the medication should be taken based on remembered schedule.

Narration:

“This is not generic small talk. The response is bound to long-term memory and designed for eldercare outcomes.”

## 0:48-1:30 Preventive reminder path

User says (or system proactively confirms):

```text
提醒我晚上八点吃降压药。
```

Expected behavior:

- Reminder tool is invoked and structured output is returned (timer type/repeat/type/label).
- Device-side actionability is demonstrated by structured data, not plain text.

Show:
- `/api/reminders` result or event list

Narration:

“Reminder output is machine action-ready. Even if network is unstable later, the local device can execute from structured data.”

## 1:30-2:16 Fraud risk interception

User says:

```text
刚才有人说我医保卡异常，让我发验证码，还要我马上转账到安全账户。
```

Expected behavior:

- Risk engine resolves to `scam_alert` (high / critical gate).
- Safety response interrupts normal companion mode immediately.
- The assistant blocks risky action recommendations and gives a concrete prevention script:
  - 不转账
  - 不报验证码
  - 先与家属/官方确认

Narration:

“This is the key technical edge: not faster answers, but **risk-first interception**.”

## 2:16-2:46 Family escalation

Triggered by the same conversation or by the assistant guidance, show family summary generation:

```text
家属提醒：用户出现疑似反诈语言行为，检测到验证码索要与转账要求。建议尽快电话核实。Trace: <trace_id>
```

Expected behavior:

- `/api/notifications` returns warning payload with:
  - category `scam_alert`
  - severity / status fields
  - trace linkage
- If provider adapter is connected, send path is executed.
- If adapter not connected yet (current roadmap), clearly state “已生成审计事件，待 provider 接入后下发” in UI/Narration.

Narration:

“Family handoff is not a UX feature only — it is a workflow boundary with escalation state.”

## 2:46-3:00 Trace audit

Open Trace detail and walk:

- `trace_id` + 时间线
- intent → emotion → risk
- memory recall summary
- tool call (`reminder` / notification payload)
- model latency (`ttft_ms`, total latency)
- final output and action outcome

Closing:

“This demo shows one closed loop: companionship, memory, safety interception, family escalation, and auditable execution. That is the difference between a chatbot and a care runtime.”

---

### Demo checkpoint mapping (technical anchors)

- Realtime channels: `/ws/chat`, `/ws/device/realtime`
- Risk-aware output behavior in backend: `risk_engine` + `risk_rules.yaml`
- Family path: `/api/notifications`, `/api/reminders`
- Auditability: trace timeline and tool/result events in `/api/traces`
