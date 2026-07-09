# Firmware (ESP32-S3) — Protocol Alignment

This tree is a **protocol-aligned firmware skeleton** for `/ws/device/realtime`.
It is intentionally honest about hardware bring-up: WiFi/ADF audio are gated
behind compile flags so reviewers can see the contract without mistaking stubs
for a production flash image.

Audio is fail-closed in this repository. Until a board-specific ESP-ADF pipeline is linked and
sets the runtime ready state, the device advertises `audio=false`, reports the pipeline as not
initialized, and refuses to send capture buffers. Protocol tests are not hardware audio evidence.

## Backend contract (device → server)

1. Connect WebSocket, first text frame:
   `{"type":"auth","auth_type":"device","device_id":"<device uuid>","credential":"<device secret>","firmware_version":"...","capabilities":{...}}`
2. After wake / listen start:
   `{"type":"audio_start","seq":1,"sample_rate":16000}`
3. Stream PCM binary frames (16-bit mono @ 16 kHz).
4. After VAD end:
   `{"type":"audio_end","seq":2}`
5. Send heartbeat and command receipts with strictly increasing `seq`; receipts include
   `command_id`, `receipt_type`, and health/firmware metadata for correlation.

Production transport is gated by `CONFIG_COMPANION_REQUIRE_WSS=1`, which rejects
non-`wss://` `CONFIG_WS_SERVER_URI` values before WebSocket initialization.

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

OTA support is interface/state only in this skeleton. Device health reports
`ota_verification_state=pending_evidence`; do not mark a firmware release
verified until real signing-key evidence and board boot/flash logs exist.

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

See `docs/evidence/device-protocol-expected-sequence-20260709.txt` for the expected two-turn
protocol sequence (host harness / annotated expected log). Real board serial
captures should replace that file when available.

## Gates

- `CONFIG_COMPANION_ENABLE_WIFI=0` (default): WiFi STA bring-up stubbed.
- `CONFIG_COMPANION_ENABLE_ADF_AUDIO=0` (default): ADF pipeline remains skeleton.
- `CONFIG_COMPANION_REQUIRE_WSS=1` (default): non-TLS device WebSocket URIs are rejected.
