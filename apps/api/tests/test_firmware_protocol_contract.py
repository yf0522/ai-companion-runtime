"""Host-side checks that firmware sources mention the backend device protocol."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MAIN_C = ROOT / "firmware" / "main" / "main.c"
REMINDER_C = ROOT / "firmware" / "main" / "local_reminder.c"


def test_firmware_sends_audio_start_end():
    text = MAIN_C.read_text(encoding="utf-8")
    assert '"audio_start"' in text
    assert '"audio_end"' in text
    assert "sample_rate" in text


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
