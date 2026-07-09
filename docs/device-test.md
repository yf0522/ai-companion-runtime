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
| Device audio receive path | Verified by automated test | Tests send binary PCM chunks after `audio_start` and before `audio_end`. |
| ASR fallback flow | Verified by automated test | Empty realtime ASR falls back to batch PCM transcription when enough PCM was received. |
| Model text stream to device | Verified by automated test | Tests assert `first_reply` and `delta` messages are streamed after ASR. |
| TTS audio stream back to device | Verified by automated test | Tests assert synthesized PCM bytes are returned and followed by `tts_done`. |
| Empty speech handling | Verified by automated test | Empty transcript returns `no_speech` and does not call model or TTS. |
| TTS API contract | Verified by automated test | `apps/api/tests/test_tts_api.py` verifies DashScope request shape and PCM response. |
| Risk detection engine | Verified by automated test | `apps/api/tests/test_risk_engine.py` covers critical, high-risk variants, negation, and safe contexts. |
| Prompt-injection wrapper | Verified by automated test | `apps/api/tests/test_prompt_injection.py` covers instruction override attempts. |
| Reminder structured output | Implemented | `apps/api/app/tools/reminder_tool.py` emits alarm/countdown/reminder fields for device-side handling. |

## Hardware Work Previously Verified

The hardware diagnosis in `docs/hardware-second-turn-diagnosis.md` records a prior ESP32-S3 device debug session:

- Device path used 16 kHz PCM capture, backend ASR, `/ws/chat`, backend TTS, and local I2S playback.
- A second-turn wake/listen bug was fixed in the firmware project by re-entering the active idle state and restarting wake triggers after playback or error paths.
- Firmware build and flash succeeded on a connected ESP32-S3 device.
- Backend tests passed at that time.
- Follow-up manual two-turn validation with serial logs was recommended.

Because that firmware project lived outside this repo at the time, this repo should currently describe that work as prior hardware validation, not as a fully reproduced CI-controlled hardware test.

## Not Yet Fully Verified

| Area | Current status |
|---|---|
| End-to-end hardware loop in this repo | Not yet fully automated. Needs a repeatable device test script and captured serial log. |
| Reminder local trigger on ESP32 | Backend emits structured timer data, but device-side local trigger verification should be documented with firmware logs. |
| Fraud detection full demo path | Risk/rule detection exists; investor demo flow should be run against a scripted scenario and captured in Trace. |
| Family notification delivery | Roadmap unless a concrete notification adapter is wired and tested. |
| Production device auth for ASR/TTS HTTP endpoints | Needs hardening: token checks, request size limits, per-device quota, and audit logs. |
| Audio format contract | Needs one documented device format. Recommended target: raw PCM 16-bit mono, 24 kHz for playback. |

## Recommended Next Test Pass

1. Start backend and web console from this repo.
2. Connect ESP32-S3 firmware to the backend using a device JWT.
3. Run two consecutive voice turns and capture serial logs.
4. Verify `connected -> listening -> asr_final -> first_reply/delta -> tts_done` for both turns.
5. Trigger a reminder command and verify the device creates and fires the local alarm/countdown.
6. Run a scripted fraud-risk utterance and verify risk classification, family-notification placeholder behavior, and Trace timeline.
7. Save logs or screenshots under `docs/evidence/` before presenting as fully hardware verified.
