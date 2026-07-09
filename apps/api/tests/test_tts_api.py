from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import tts


def test_synthesize_returns_dashscope_pcm(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    pcm = b"\x01\x00\x02\x00"

    class FakeResponse:
        status_code = 200

        def __init__(self, content: bytes = b"") -> None:
            self.content = content
            self.text = ""

        def json(self) -> dict[str, object]:
            return {"output": {"audio": {"url": "https://audio.example/test.pcm"}}}

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        async def post(self, url: str, headers: dict[str, str], json: dict[str, object]) -> FakeResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

        async def get(self, url: str) -> FakeResponse:
            captured["audio_url"] = url
            return FakeResponse(content=pcm)

    class FakeHttpx:
        AsyncClient = FakeAsyncClient

    monkeypatch.setattr(tts.settings, "qwen_api_key", "test-key")
    monkeypatch.setattr(tts, "httpx", FakeHttpx, raising=False)

    app = FastAPI()
    app.include_router(tts.router)
    client = TestClient(app)

    response = client.post("/v1/synthesize", json={"text": "你好", "format": "mp3", "voice": "zh_female_warm"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/pcm"
    assert response.content == pcm
    assert captured["url"].endswith("/api/v1/services/audio/tts/SpeechSynthesizer")
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"] == {
        "model": "cosyvoice-v3-flash",
        "input": {
            "text": "你好",
            "voice": "longanyang",
            "format": "pcm",
            "sample_rate": 24000,
        },
    }
