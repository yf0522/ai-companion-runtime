# Firmware (ESP32-S3) — Protocol Alignment

This tree is a **protocol-aligned firmware skeleton** for `/ws/device/realtime`.
It is intentionally honest about hardware bring-up: WiFi/ADF audio are gated
behind compile flags so reviewers can see the contract without mistaking stubs
for a production flash image.

## Backend contract (device → server)

1. Connect WebSocket, first text frame:
   `{"type":"auth","token":"<JWT>"}`
2. After wake / listen start:
   `{"type":"audio_start","sample_rate":16000}`
3. Stream PCM binary frames (16-bit mono @ 16 kHz).
4. After VAD end:
   `{"type":"audio_end"}`

## Backend contract (server → device)

Handled in `main/main.c` `on_ws_text`:

| type | device action |
|---|---|
| `connected` | log |
| `listening` | log |
| `trace` | log `trace_id` |
| `asr_partial` / `asr_final` | log transcript |
| `risk_alert` | enter SPEAKING / safety path |
| `first_reply` / `delta` | enter SPEAKING (PCM may follow as binary) |
| `reminder_create` | persist via `local_reminder_add_structured` (NVS) |
| `tool_status` / `tool_result` | log |
| `final` | log |
| `tts_done` | return to LISTENING (second-turn ready) |
| `no_speech` / `error` | return to LISTENING |

## Build / flash (when ESP-IDF is installed)

```bash
cd firmware
idf.py set-target esp32s3
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

Without ESP-IDF on the host, treat this PR as **protocol + reminder NVS alignment**.
Do not claim a full hardware closed loop until serial evidence is captured.

## Evidence

See `docs/evidence/device-serial-log-20260709.txt` for the expected two-turn
protocol sequence (host harness / annotated expected log). Real board serial
captures should replace that file when available.

## Gates

- `CONFIG_COMPANION_ENABLE_WIFI=0` (default): WiFi STA bring-up stubbed.
- `CONFIG_COMPANION_ENABLE_ADF_AUDIO=0` (default): ADF pipeline remains skeleton.
