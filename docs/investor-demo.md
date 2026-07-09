# Investor Demo Script

Target length: 3 minutes

Demo theme: an eldercare AI companion that combines voice companionship, medication reminders, fraud-risk recognition, family escalation, and traceable runtime observability.

## Setup

- Backend API running on `http://localhost:8000`.
- Web console running on `http://localhost:3000`.
- Device or simulated device connected through WebSocket.
- Trace view open in the browser.
- Prepared user profile: elderly user living alone, family contact enabled.

## 0:00-0:20 Opening

"This is AI Companion Runtime, a realtime companion and safety runtime for eldercare devices. The key point is not just chat. It can respond quickly, recognize risk, trigger tools such as reminders or notifications, and leave a trace of what happened."

Show the device or chat console connected, then show the Trace panel waiting for a new session.

## 0:20-1:00 Medication Reminder

User says:

```text
提醒我晚上八点吃降压药。
```

Expected demo behavior:

- Runtime recognizes reminder intent.
- Assistant confirms the medication reminder in natural language.
- Tool result includes structured reminder data such as label, time, timer type, and repeat mode.
- Device path can use the structured data to create a local alarm/countdown.

Narration:

"The reminder is not only text. The tool returns structured timer data so the device can trigger locally even if the network is unstable later."

## 1:00-1:45 Fraud Recognition

User says:

```text
刚才有人打电话说我银行卡有风险，让我把验证码告诉他，还要我马上转账到安全账户。
```

Expected demo behavior:

- Assistant switches from casual companionship to safety guidance.
- It identifies suspicious fraud indicators: verification code request, urgent transfer, and 'safe account'.
- It tells the user not to share codes or transfer money.
- It proposes calling family or an official bank number.

Narration:

"This is where eldercare differs from a generic chatbot. The runtime treats certain intents as safety-sensitive and changes the response policy immediately."

## 1:45-2:25 Family Notification

Assistant/tool flow:

```text
我可以帮你通知家属，让他们确认这通电话是否可信。
```

Expected demo behavior:

- If notification adapter is enabled: send a family alert with summary and trace ID.
- If adapter is not enabled yet: show the notification as a roadmap placeholder and explain the adapter boundary.

Suggested alert content:

```text
家属提醒：用户收到疑似诈骗电话，对方要求验证码和转账。建议尽快电话确认。Trace: <trace_id>
```

Narration:

"For families, the product value is the escalation path. The assistant does not just answer; it creates an auditable handoff."

## 2:25-3:00 Trace

Open the Trace detail.

Show:

- `trace_id`
- Intent and risk analysis
- First reply latency
- Tool call status and result
- Final response
- Cost and latency fields if available

Narration:

"Every critical interaction can be inspected after the fact. That matters for safety, debugging, model cost, and trust with care providers."

## Close

"The current repo contains the realtime runtime, model routing, risk engine, tool dispatch, trace observability, and the device realtime WebSocket path. The roadmap is to harden device auth, finish family notification adapters, and collect repeatable hardware evidence for the full ESP32-S3 flow."
