from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import ws_device_realtime
from app.api.auth import create_token


def test_device_realtime_auth_and_audio_roundtrip(monkeypatch):
    class FakeRealtimeAsrSession:
        def __init__(self, sample_rate: int) -> None:
            raise AssertionError("realtime ASR session should not be used")

        async def start(self) -> None:
            return None

        def send_audio(self, data: bytes) -> None:
            self.pcm.extend(data)

        async def next_event(self, timeout: float = 0.0):
            return None

        async def stop(self) -> str:
            return ""

    async def fake_transcribe(pcm_data: bytes, sample_rate: int = 16000) -> str:
        assert sample_rate == 16000
        assert pcm_data == b"\x01\x02\x03\x04"
        return "天气怎么样？"

    async def fake_reply(text: str):
        assert text == "天气怎么样？"
        yield "今天天气"
        yield "不错。"

    async def fake_stream_tts(text: str):
        assert text == "今天天气不错。"
        yield b"pcm-audio"

    monkeypatch.setattr(ws_device_realtime, "RealtimeAsrSession", FakeRealtimeAsrSession)
    monkeypatch.setattr(ws_device_realtime, "transcribe_pcm", fake_transcribe)
    monkeypatch.setattr(ws_device_realtime, "stream_reply_text", fake_reply)
    monkeypatch.setattr(ws_device_realtime, "stream_synthesize_pcm", fake_stream_tts)

    app = FastAPI()
    app.include_router(ws_device_realtime.router)
    client = TestClient(app)
    token = create_token("device-user", "esp32-device")

    with client.websocket_connect("/ws/device/realtime") as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["type"] == "connected"

        ws.send_json({"type": "audio_start", "sample_rate": 16000})
        assert ws.receive_json()["type"] == "listening"
        ws.send_bytes(b"\x01\x02")
        ws.send_bytes(b"\x03\x04")
        ws.send_json({"type": "audio_end"})

        assert ws.receive_json() == {"type": "asr_final", "text": "天气怎么样？"}
        assert ws.receive_json() == {"type": "first_reply", "text": "今天天气"}
        assert ws.receive_json() == {"type": "delta", "text": "不错。"}
        assert ws.receive_bytes() == b"pcm-audio"
        assert ws.receive_json()["type"] == "tts_done"


def test_device_realtime_empty_asr_does_not_call_model_or_tts(monkeypatch):
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

    async def fail_reply(text: str):
        raise AssertionError("model should not be called for empty ASR")
        yield ""

    async def fail_stream_tts(text: str):
        raise AssertionError("TTS should not be called for empty ASR")
        yield b""

    monkeypatch.setattr(ws_device_realtime, "RealtimeAsrSession", FakeRealtimeAsrSession)
    monkeypatch.setattr(ws_device_realtime, "stream_reply_text", fail_reply)
    monkeypatch.setattr(ws_device_realtime, "stream_synthesize_pcm", fail_stream_tts)

    app = FastAPI()
    app.include_router(ws_device_realtime.router)
    client = TestClient(app)
    token = create_token("device-user", "esp32-device")

    with client.websocket_connect("/ws/device/realtime") as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["type"] == "connected"

        ws.send_json({"type": "audio_start", "sample_rate": 16000})
        assert ws.receive_json()["type"] == "listening"
        ws.send_bytes(b"\x00\x00\x00\x00")
        ws.send_json({"type": "audio_end"})

        assert ws.receive_json() == {"type": "asr_final", "text": ""}
        assert ws.receive_json() == {"type": "no_speech", "reason": "empty_transcript"}


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

    async def fake_reply(text: str):
        assert text == "后备识别文本"
        yield "收到。"

    async def fake_stream_tts(text: str):
        assert text == "收到。"
        yield b"fallback-pcm"

    monkeypatch.setattr(ws_device_realtime, "RealtimeAsrSession", FakeRealtimeAsrSession)
    monkeypatch.setattr(ws_device_realtime, "transcribe_pcm", fake_transcribe)
    monkeypatch.setattr(ws_device_realtime, "stream_reply_text", fake_reply)
    monkeypatch.setattr(ws_device_realtime, "stream_synthesize_pcm", fake_stream_tts)

    app = FastAPI()
    app.include_router(ws_device_realtime.router)
    client = TestClient(app)
    token = create_token("device-user", "esp32-device")

    with client.websocket_connect("/ws/device/realtime") as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["type"] == "connected"

        ws.send_json({"type": "audio_start", "sample_rate": 16000})
        assert ws.receive_json()["type"] == "listening"
        ws.send_bytes(b"\x01\x02" * 400)
        ws.send_json({"type": "audio_end"})

        assert ws.receive_json() == {"type": "asr_final", "text": "后备识别文本"}
        assert ws.receive_json() == {"type": "first_reply", "text": "收到。"}
        assert ws.receive_bytes() == b"fallback-pcm"
        assert ws.receive_json()["type"] == "tts_done"
