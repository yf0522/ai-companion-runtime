# Device Test Status

Last updated: 2026-07-09

This document records what has been verified for the elder companion device path and what is still roadmap. The goal is to make the repo status clear for reviewers, investors, and grant/application follow-up.

## Scope

The runtime now treats `https://github.com/yf0522/ai-companion-runtime` as the canonical repository for the AI companion backend, web console, and eldercare device integration work. Earlier device work from `https://github.com/yf0522/elder-companion-runtime` is being consolidated into this repo.

## Verified In This Repo

| Area | Status | Evidence |
|---|---|---|
| Browser chat WebSocket | Implemented and covered by backend runtime/tests | `/ws/chat` protocol is documented in `README.md`; backend tests cover engines and runtime pieces. |
| Device realtime WebSocket route | Implemented | `apps/api/app/api/ws_device_realtime.py` exposes `/ws/device/realtime`. |
| Device JWT auth | Verified by automated test | `apps/api/tests/test_ws_device_realtime.py` authenticates with a generated JWT before audio exchange. |
| Device audio receive path | 协议行为已验证（测试桩/替身） | 在单测中验证 `audio_start` 后发送 PCM 帧、接收 `listening`、`asr_final`。 |
| ASR fallback flow | 协议行为已验证（测试桩/替身） | 空闲分支触发时会回退到 batch ASR。 |
| Model text stream to device | 协议行为已验证（测试桩/替身） | 用桩化模型流验证 `first_reply`/`delta` 顺序。 |
| TTS audio stream back to device | 协议行为已验证（测试桩/替身） | 用桩化 TTS 验证返回 PCM 与 `tts_done`。 |
| Empty speech handling | 协议行为已验证（测试桩/替身） | 空转录返回 `no_speech`，不调用模型/TTS。 |
| TTS API contract | 集成依赖前提（测试桩/替身） | `apps/api/tests/test_tts_api.py` 通过 monkeypatch 约束请求参数与返回；未覆盖真实 DashScope 可用性。 |
| Risk detection engine | 协议行为已验证（测试桩/替身） | `apps/api/tests/test_risk_engine.py` 覆盖 fraud / health / emotional 的分类、否定词与安全上下文。 |
| Prompt-injection wrapper | 已验证（测试桩/替身） | `apps/api/tests/test_prompt_injection.py` 覆盖指令注入与优先级。 |
| Reminder structured output | 已实现 | `apps/api/app/tools/reminder_tool.py` 输出 `reminder_create` 结构体，用于设备侧闹钟/倒计时消费。 |

## Hardware Work Previously Verified

The hardware diagnosis referenced in legacy notes records a prior ESP32-S3 device debug session:

- Device path used 16 kHz PCM capture, backend ASR, `/ws/chat`, backend TTS, and local I2S playback.
- A second-turn wake/listen bug was fixed in the firmware project by re-entering the active idle state and restarting wake triggers after playback or error paths.
- Firmware build and flash succeeded on a connected ESP32-S3 device.
- Backend tests passed at that time.
- Follow-up manual two-turn validation with serial logs was recommended.

Because the firmware project and serial logs historically lived outside this repo, older notes treated hardware as historical reference. Protocol-aligned firmware source plus an **expected** (annotated) sequence doc may land under `docs/evidence/`; replace annotated sequences with live `idf.py monitor` captures before claiming a full hardware closed loop.

## Not Yet Fully Verified

| Area | Current status |
|---|---|
| End-to-end hardware loop in this repo | Protocol alignment may be in source; live flash + real serial still required. |
| Reminder local trigger on ESP32 | Firmware NVS consume may land with protocol work; need real serial fire logs for diligence. |
| Fraud detection full demo path | Risk/rule detection exists; investor demo flow should be run against a scripted scenario and captured in Trace. |
| Family notification delivery | `NotificationLog` 事件已落库；推送 provider 与真实回执/送达链路仍在 roadmap。 |
| Production device auth for ASR/TTS HTTP endpoints | Needs hardening: token checks, request size limits, per-device quota, and audit logs. |
| Audio format contract | Needs one documented device format. Recommended target: raw PCM 16-bit mono, 24 kHz for playback. |

## Recommended Next Test Pass

1. Start backend and web console from this repo.
2. Connect ESP32-S3 firmware to the backend using a device JWT.
3. Run two consecutive voice turns and capture serial logs.
4. Verify `connected -> listening -> asr_final -> first_reply/delta -> tts_done` for both turns.
5. Trigger a reminder command and verify the device creates and fires the local alarm/countdown.
6. Run a scripted fraud-risk utterance and verify risk classification, family-notification persistence (`/api/notifications`), and Trace timeline.
7. Save logs or screenshots under `docs/evidence/` before presenting as fully hardware verified.
