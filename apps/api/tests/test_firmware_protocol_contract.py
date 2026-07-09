"""Host-side checks that firmware sources mention the backend device protocol."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MAIN_C = ROOT / "firmware" / "main" / "main.c"
REMINDER_C = ROOT / "firmware" / "main" / "local_reminder.c"
WS_CLIENT_C = ROOT / "firmware" / "main" / "ws_client.c"
CONFIG_H = ROOT / "firmware" / "main" / "config.h"
AUDIO_PIPELINE_C = ROOT / "firmware" / "main" / "audio_pipeline.c"


def test_firmware_sends_audio_start_end():
    text = MAIN_C.read_text(encoding="utf-8")
    assert '"audio_start"' in text
    assert '"audio_end"' in text
    assert "sample_rate" in text
    assert "ws_client_send_json_with_seq" in text


def test_firmware_handles_backend_event_types():
    text = MAIN_C.read_text(encoding="utf-8")
    for event in (
        "connected",
        "trace",
        "asr_partial",
        "asr_final",
        "risk_alert",
        "first_reply",
        "delta",
        "reminder_create",
        "tool_status",
        "tool_result",
        "final",
        "tts_done",
        "error",
    ):
        assert f'"{event}"' in text, f"missing handler for {event}"


def test_firmware_consumes_reminder_create_with_id():
    main_text = MAIN_C.read_text(encoding="utf-8")
    rem_text = REMINDER_C.read_text(encoding="utf-8")
    assert "handle_reminder_create" in main_text
    assert "local_reminder_add_structured" in rem_text
    assert "reminder_id" in rem_text


def test_firmware_uses_device_auth_not_user_jwt():
    text = WS_CLIENT_C.read_text(encoding="utf-8")
    assert '"auth_type"' in text
    assert '"device"' in text
    assert '"device_id"' in text
    assert '"credential"' in text
    assert '"token"' not in text


def test_firmware_reports_health_receipts_and_pending_ota_evidence():
    ws_text = WS_CLIENT_C.read_text(encoding="utf-8")
    main_text = MAIN_C.read_text(encoding="utf-8")
    assert '"heartbeat"' in ws_text
    assert '"ota_verification_state"' in ws_text
    assert '"pending_evidence"' in ws_text
    assert '"receipt"' in main_text
    assert '"command_id"' in main_text
    assert '"receipt_type"' in main_text


def test_firmware_validates_secure_transport_configuration():
    ws_text = WS_CLIENT_C.read_text(encoding="utf-8")
    config_text = CONFIG_H.read_text(encoding="utf-8")
    assert "CONFIG_COMPANION_REQUIRE_WSS" in config_text
    assert '"wss://"' in ws_text
    assert "Invalid device transport config" in ws_text


def test_firmware_audio_is_fail_closed_until_real_pipeline_is_ready():
    pipeline_text = AUDIO_PIPELINE_C.read_text(encoding="utf-8")
    main_text = MAIN_C.read_text(encoding="utf-8")
    ws_text = WS_CLIENT_C.read_text(encoding="utf-8")
    assert "return 0;" in pipeline_text
    assert "audio_pipeline_is_ready" in main_text
    assert '"audio", audio_pipeline_is_ready()' in ws_text
    assert '"audio_pipeline_initialized", audio_pipeline_is_ready()' in ws_text
