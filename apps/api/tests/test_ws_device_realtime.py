from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import ws_device_realtime
from app.runtime import device_stream_manager
from app.runtime.device_identity import DevicePrincipal
from app.runtime.stream_manager import StreamManager


class _FakeHarness:
    def __init__(self, mode: str = "normal"):
        self.mode = mode
        self.calls: list[dict] = []

    async def run(self, user_id, session_id, message, stream_mgr: StreamManager, cancel_event):
        self.calls.append(
            {
                "user_id": user_id,
                "session_id": session_id,
                "message": message,
            }
        )
        await stream_mgr.send_trace("trace_device_1")
        if self.mode == "scam":
            await stream_mgr.send_risk_alert("high", "疑似诈骗，请先挂断")
            await stream_mgr.send_first_reply("不要转账，也不要发验证码。", 12)
            await stream_mgr.send_final("trace_device_1", "m1", 12, 40, [], False)
            return {"trace_id": "trace_device_1", "blocked_by_risk": True}
        if self.mode == "reminder":
            await stream_mgr.send_first_reply("好的，已帮您设好提醒。", 10)
            await stream_mgr.send_reminder_create(
                {
                    "label": "降压药",
                    "timer_type": "alarm",
                    "hour": 20,
                    "minute": 0,
                    "repeat_mode": "daily",
                }
            )
            await stream_mgr.send_final("trace_device_1", "m1", 10, 35, ["reminder"], True)
            return {"trace_id": "trace_device_1", "tools_used": ["reminder"]}

        await stream_mgr.send_first_reply("今天天气", 8)
        await stream_mgr.send_delta("不错。")
        await stream_mgr.send_final("trace_device_1", "m1", 8, 30, [], True)
        return {"trace_id": "trace_device_1"}


def _device_auth(seq: int | None = None) -> dict:
    data = {
        "type": "auth",
        "auth_type": "device",
        "device_id": "77777777-7777-7777-7777-777777777777",
        "credential": "device-secret",
        "firmware_version": "0.4.0",
        "capabilities": {"audio": True, "receipts": True},
    }
    if seq is not None:
        data["seq"] = seq
    return data


async def _fake_device_principal(data: dict):
    if data.get("credential") != "device-secret":
        return None
    return DevicePrincipal(
        device_id=data["device_id"],
        user_id="device-user",
        external_id="esp32-test",
        capabilities=data.get("capabilities") or {},
        firmware_version=data.get("firmware_version"),
    )


def _patch_device_auth(monkeypatch):
    persisted: list[dict] = []

    async def fake_advance_device_sequence(db, **kwargs):
        persisted.append(kwargs)
        return None

    monkeypatch.setattr(
        ws_device_realtime,
        "authenticate_device_from_message",
        _fake_device_principal,
    )
    monkeypatch.setattr(
        ws_device_realtime,
        "advance_device_sequence",
        fake_advance_device_sequence,
    )
    return persisted


def test_device_realtime_auth_and_audio_roundtrip(monkeypatch):
    class FakeRealtimeAsrSession:
        def __init__(self, sample_rate: int) -> None:
            raise AssertionError("realtime ASR session should not be used")

    async def fake_transcribe(pcm_data: bytes, sample_rate: int = 16000) -> str:
        assert sample_rate == 16000
        assert pcm_data == b"\x01\x02\x03\x04"
        return "天气怎么样？"

    async def fake_stream_tts(text: str):
        assert text == "今天天气不错。"
        yield b"pcm-audio"

    harness = _FakeHarness("normal")

    async def fake_ensure(user_id: str, session_id: str | None = None) -> str:
        return "11111111-1111-1111-1111-111111111111"

    monkeypatch.setattr(ws_device_realtime, "RealtimeAsrSession", FakeRealtimeAsrSession)
    monkeypatch.setattr(ws_device_realtime, "transcribe_pcm", fake_transcribe)
    monkeypatch.setattr(device_stream_manager, "stream_synthesize_pcm", fake_stream_tts)
    persisted = _patch_device_auth(monkeypatch)
    monkeypatch.setattr(ws_device_realtime, "get_agent_runtime", lambda _name=None: harness)
    async def fake_increment(sid: str) -> None:
        return None

    monkeypatch.setattr(ws_device_realtime.session_service, "ensure_session", fake_ensure)
    monkeypatch.setattr(
        ws_device_realtime.session_service,
        "increment_message_count",
        fake_increment,
    )

    app = FastAPI()
    app.include_router(ws_device_realtime.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/device/realtime") as ws:
        ws.send_json(_device_auth())
        connected = ws.receive_json()
        assert connected["type"] == "connected"
        assert connected["session_id"] == "11111111-1111-1111-1111-111111111111"
        assert connected["device_id"] == "77777777-7777-7777-7777-777777777777"
        assert connected["protocol"]["max_audio_frame_bytes"] > 0

        ws.send_json({"type": "audio_start", "seq": 1, "sample_rate": 16000})
        assert ws.receive_json()["type"] == "listening"
        ws.send_bytes(b"\x01\x02")
        ws.send_bytes(b"\x03\x04")
        ws.send_json({"type": "audio_end", "seq": 2})

        assert ws.receive_json() == {"type": "asr_final", "text": "天气怎么样？"}
        assert ws.receive_json() == {"type": "trace", "trace_id": "trace_device_1"}
        assert ws.receive_json() == {"type": "first_reply", "text": "今天天气", "ttft_ms": 8}
        assert ws.receive_json() == {"type": "delta", "text": "不错。"}
        final = ws.receive_json()
        assert final["type"] == "final"
        assert ws.receive_bytes() == b"pcm-audio"
        assert ws.receive_json()["type"] == "tts_done"

    assert harness.calls[0]["message"] == "天气怎么样？"
    assert [item["sequence"] for item in persisted] == [1, 2]


def test_device_realtime_empty_asr_does_not_call_harness(monkeypatch):
    class FakeRealtimeAsrSession:
        def __init__(self, sample_rate: int) -> None:
            assert sample_rate == 16000

        async def start(self) -> None:
            return None

        def send_audio(self, data: bytes) -> None:
            return None

        async def next_event(self, timeout: float = 0.0):
            return None

        async def stop(self) -> str:
            return ""

    harness = _FakeHarness("normal")

    async def fake_ensure(user_id: str, session_id: str | None = None) -> str:
        return "22222222-2222-2222-2222-222222222222"

    monkeypatch.setattr(ws_device_realtime, "RealtimeAsrSession", FakeRealtimeAsrSession)
    monkeypatch.setattr(ws_device_realtime, "get_agent_runtime", lambda _name=None: harness)
    monkeypatch.setattr(ws_device_realtime.session_service, "ensure_session", fake_ensure)
    _patch_device_auth(monkeypatch)

    app = FastAPI()
    app.include_router(ws_device_realtime.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/device/realtime") as ws:
        ws.send_json(_device_auth())
        assert ws.receive_json()["type"] == "connected"

        ws.send_json({"type": "audio_start", "seq": 1, "sample_rate": 16000})
        assert ws.receive_json()["type"] == "listening"
        ws.send_bytes(b"\x00\x00\x00\x00")
        ws.send_json({"type": "audio_end", "seq": 2})

        assert ws.receive_json() == {"type": "asr_final", "text": ""}
        assert ws.receive_json() == {"type": "no_speech", "reason": "empty_transcript"}

    assert harness.calls == []


def test_device_realtime_falls_back_to_batch_asr_when_realtime_returns_empty(monkeypatch):
    class FakeRealtimeAsrSession:
        def __init__(self, sample_rate: int) -> None:
            assert sample_rate == 16000

        async def start(self) -> None:
            return None

        def send_audio(self, data: bytes) -> None:
            return None

        async def next_event(self, timeout: float = 0.0):
            return None

        async def stop(self) -> str:
            return ""

    async def fake_transcribe(pcm_data: bytes, sample_rate: int = 16000) -> str:
        assert sample_rate == 16000
        assert len(pcm_data) == 800
        return "后备识别文本"

    async def fake_stream_tts(text: str):
        assert text == "今天天气不错。" or text == "收到。"
        yield b"fallback-pcm"

    harness = _FakeHarness("normal")
    # Override normal reply for this case
    async def run(self, user_id, session_id, message, stream_mgr, cancel_event):
        harness.calls.append({"message": message})
        await stream_mgr.send_trace("trace_fb")
        await stream_mgr.send_first_reply("收到。", 5)
        await stream_mgr.send_final("trace_fb", "m1", 5, 20, [], True)
        return {"trace_id": "trace_fb"}

    harness.run = run.__get__(harness, _FakeHarness)

    async def fake_ensure(user_id: str, session_id: str | None = None) -> str:
        return "33333333-3333-3333-3333-333333333333"

    monkeypatch.setattr(ws_device_realtime, "RealtimeAsrSession", FakeRealtimeAsrSession)
    monkeypatch.setattr(ws_device_realtime, "transcribe_pcm", fake_transcribe)
    monkeypatch.setattr(device_stream_manager, "stream_synthesize_pcm", fake_stream_tts)
    _patch_device_auth(monkeypatch)
    async def fake_increment(sid: str) -> None:
        return None

    monkeypatch.setattr(ws_device_realtime, "get_agent_runtime", lambda _name=None: harness)
    monkeypatch.setattr(ws_device_realtime.session_service, "ensure_session", fake_ensure)
    monkeypatch.setattr(
        ws_device_realtime.session_service,
        "increment_message_count",
        fake_increment,
    )

    app = FastAPI()
    app.include_router(ws_device_realtime.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/device/realtime") as ws:
        ws.send_json(_device_auth())
        assert ws.receive_json()["type"] == "connected"

        ws.send_json({"type": "audio_start", "seq": 1, "sample_rate": 16000})
        assert ws.receive_json()["type"] == "listening"
        ws.send_bytes(b"\x01\x02" * 400)
        ws.send_json({"type": "audio_end", "seq": 2})

        assert ws.receive_json() == {"type": "asr_final", "text": "后备识别文本"}
        assert ws.receive_json()["type"] == "trace"
        assert ws.receive_json()["type"] == "first_reply"
        assert ws.receive_json()["type"] == "final"
        assert ws.receive_bytes() == b"fallback-pcm"
        assert ws.receive_json()["type"] == "tts_done"


def test_device_scam_utterance_goes_through_harness_risk_path(monkeypatch):
    async def fake_transcribe(pcm_data: bytes, sample_rate: int = 16000) -> str:
        return "让我把验证码发给你并转账到安全账户"

    async def fake_stream_tts(text: str):
        assert "验证码" in text or "转账" in text or "诈骗" in text
        yield b"risk-pcm"

    harness = _FakeHarness("scam")

    async def fake_ensure(user_id: str, session_id: str | None = None) -> str:
        return "44444444-4444-4444-4444-444444444444"

    monkeypatch.setattr(ws_device_realtime, "transcribe_pcm", fake_transcribe)
    monkeypatch.setattr(device_stream_manager, "stream_synthesize_pcm", fake_stream_tts)
    _patch_device_auth(monkeypatch)
    async def fake_increment(sid: str) -> None:
        return None

    monkeypatch.setattr(ws_device_realtime, "get_agent_runtime", lambda _name=None: harness)
    monkeypatch.setattr(ws_device_realtime.session_service, "ensure_session", fake_ensure)
    monkeypatch.setattr(
        ws_device_realtime.session_service,
        "increment_message_count",
        fake_increment,
    )

    app = FastAPI()
    app.include_router(ws_device_realtime.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/device/realtime") as ws:
        ws.send_json(_device_auth())
        assert ws.receive_json()["type"] == "connected"
        ws.send_json({"type": "audio_start", "seq": 1, "sample_rate": 16000})
        assert ws.receive_json()["type"] == "listening"
        ws.send_bytes(b"\x01" * 700)
        ws.send_json({"type": "audio_end", "seq": 2})

        assert ws.receive_json()["type"] == "asr_final"
        assert ws.receive_json()["type"] == "trace"
        assert ws.receive_json()["type"] == "risk_alert"
        assert ws.receive_json()["type"] == "first_reply"
        assert ws.receive_json()["type"] == "final"
        assert ws.receive_bytes() == b"risk-pcm"
        assert ws.receive_json()["type"] == "tts_done"

    assert "验证码" in harness.calls[0]["message"]


def test_device_reminder_utterance_emits_reminder_create(monkeypatch):
    async def fake_transcribe(pcm_data: bytes, sample_rate: int = 16000) -> str:
        return "提醒我晚上八点吃降压药"

    async def fake_stream_tts(text: str):
        yield b"reminder-pcm"

    harness = _FakeHarness("reminder")

    async def fake_ensure(user_id: str, session_id: str | None = None) -> str:
        return "55555555-5555-5555-5555-555555555555"

    monkeypatch.setattr(ws_device_realtime, "transcribe_pcm", fake_transcribe)
    monkeypatch.setattr(device_stream_manager, "stream_synthesize_pcm", fake_stream_tts)
    _patch_device_auth(monkeypatch)
    async def fake_increment(sid: str) -> None:
        return None

    monkeypatch.setattr(ws_device_realtime, "get_agent_runtime", lambda _name=None: harness)
    monkeypatch.setattr(ws_device_realtime.session_service, "ensure_session", fake_ensure)
    monkeypatch.setattr(
        ws_device_realtime.session_service,
        "increment_message_count",
        fake_increment,
    )

    app = FastAPI()
    app.include_router(ws_device_realtime.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/device/realtime") as ws:
        ws.send_json(_device_auth())
        assert ws.receive_json()["type"] == "connected"
        ws.send_json({"type": "audio_start", "seq": 1})
        assert ws.receive_json()["type"] == "listening"
        ws.send_bytes(b"\x02" * 700)
        ws.send_json({"type": "audio_end", "seq": 2})

        assert ws.receive_json()["type"] == "asr_final"
        assert ws.receive_json()["type"] == "trace"
        assert ws.receive_json()["type"] == "first_reply"
        reminder = ws.receive_json()
        assert reminder["type"] == "reminder_create"
        assert reminder["label"] == "降压药"
        assert ws.receive_json()["type"] == "final"
        assert ws.receive_bytes() == b"reminder-pcm"
        assert ws.receive_json()["type"] == "tts_done"


def test_device_realtime_rejects_user_jwt_auth_shape():
    app = FastAPI()
    app.include_router(ws_device_realtime.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/device/realtime") as ws:
        ws.send_json({"type": "auth", "token": "user-jwt-is-not-device-auth"})
        error = ws.receive_json()
        assert error == {"type": "error", "code": "auth_required", "retry": False}


def test_device_realtime_rejects_replayed_sequence(monkeypatch):
    _patch_device_auth(monkeypatch)

    async def fake_ensure(user_id: str, session_id: str | None = None) -> str:
        return "66666666-6666-6666-6666-666666666666"

    monkeypatch.setattr(ws_device_realtime.session_service, "ensure_session", fake_ensure)
    app = FastAPI()
    app.include_router(ws_device_realtime.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/device/realtime") as ws:
        ws.send_json(_device_auth())
        assert ws.receive_json()["type"] == "connected"
        ws.send_json({"type": "ping", "seq": 1})
        assert ws.receive_json() == {"type": "pong", "seq": 1}
        ws.send_json({"type": "ping", "seq": 1})
        assert ws.receive_json() == {"type": "error", "code": "sequence_replay", "retry": False}


def test_device_realtime_rejects_sequence_when_db_watermark_wins(monkeypatch):
    async def fake_advance_device_sequence(db, **kwargs):
        assert kwargs["sequence"] == 1
        raise ValueError("sequence_replay")

    monkeypatch.setattr(
        ws_device_realtime,
        "authenticate_device_from_message",
        _fake_device_principal,
    )
    monkeypatch.setattr(
        ws_device_realtime,
        "advance_device_sequence",
        fake_advance_device_sequence,
    )

    async def fake_ensure(user_id: str, session_id: str | None = None) -> str:
        return "66666666-6666-6666-6666-666666666667"

    monkeypatch.setattr(ws_device_realtime.session_service, "ensure_session", fake_ensure)
    app = FastAPI()
    app.include_router(ws_device_realtime.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/device/realtime") as ws:
        ws.send_json(_device_auth())
        assert ws.receive_json()["type"] == "connected"
        ws.send_json({"type": "ping", "seq": 1})
        assert ws.receive_json() == {"type": "error", "code": "sequence_replay", "retry": False}


def test_device_realtime_rejects_oversized_audio_frame(monkeypatch):
    _patch_device_auth(monkeypatch)

    async def fake_ensure(user_id: str, session_id: str | None = None) -> str:
        return "99999999-9999-9999-9999-999999999999"

    monkeypatch.setattr(ws_device_realtime.session_service, "ensure_session", fake_ensure)
    app = FastAPI()
    app.include_router(ws_device_realtime.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/device/realtime") as ws:
        ws.send_json(_device_auth())
        assert ws.receive_json()["type"] == "connected"
        ws.send_json({"type": "audio_start", "seq": 1, "sample_rate": 16000})
        assert ws.receive_json()["type"] == "listening"
        ws.send_bytes(b"x" * (ws_device_realtime.MAX_AUDIO_FRAME_BYTES + 1))
        assert ws.receive_json() == {"type": "error", "code": "audio_frame_too_large", "retry": False}


def test_device_realtime_requires_receipt_correlation(monkeypatch):
    _patch_device_auth(monkeypatch)

    async def fake_ensure(user_id: str, session_id: str | None = None) -> str:
        return "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    monkeypatch.setattr(ws_device_realtime.session_service, "ensure_session", fake_ensure)
    app = FastAPI()
    app.include_router(ws_device_realtime.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/device/realtime") as ws:
        ws.send_json(_device_auth())
        assert ws.receive_json()["type"] == "connected"
        ws.send_json({"type": "receipt", "seq": 1, "receipt_type": "played"})
        assert ws.receive_json() == {
            "type": "error",
            "code": "receipt_correlation_required",
            "retry": False,
        }


def test_device_realtime_persists_heartbeat_and_receipt_metadata(monkeypatch):
    persisted = _patch_device_auth(monkeypatch)

    async def fake_ensure(user_id: str, session_id: str | None = None) -> str:
        return "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    monkeypatch.setattr(ws_device_realtime.session_service, "ensure_session", fake_ensure)
    app = FastAPI()
    app.include_router(ws_device_realtime.router)
    client = TestClient(app)

    with client.websocket_connect("/ws/device/realtime") as ws:
        ws.send_json(_device_auth())
        assert ws.receive_json()["type"] == "connected"
        ws.send_json(
            {
                "type": "heartbeat",
                "seq": 1,
                "firmware_version": "0.4.1",
                "health": {"wifi_rssi": -62, "ota_verification_state": "pending_evidence"},
            }
        )
        assert ws.receive_json()["type"] == "heartbeat_ack"
        ws.send_json(
            {
                "type": "receipt",
                "seq": 2,
                "command_id": "cmd-1",
                "receipt_type": "played",
                "metadata": {"latency_ms": 30},
            }
        )
        assert ws.receive_json() == {
            "type": "receipt_ack",
            "seq": 2,
            "command_id": "cmd-1",
            "receipt_type": "played",
        }

    assert persisted[0]["sequence"] == 1
    assert persisted[0]["health"]["ota_verification_state"] == "pending_evidence"
    assert persisted[1]["command_id"] == "cmd-1"
    assert persisted[1]["receipt_metadata"] == {"latency_ms": 30}
