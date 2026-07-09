from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import tts
from app.api.auth import create_token
from app.api.rate_limiter import clear_memory_store
from app.config import settings as settings_mod


def _auth_headers(user_id: str = "4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf") -> dict[str, str]:
    token = create_token(user_id, "audio-user", role="elder")
    return {"Authorization": f"Bearer {token}"}


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(tts.router)
    return app


def test_synthesize_requires_token() -> None:
    client = TestClient(_app())
    response = client.post("/v1/synthesize", json={"text": "你好"})
    assert response.status_code == 401


def test_synthesize_rejects_invalid_token() -> None:
    client = TestClient(_app())
    response = client.post(
        "/v1/synthesize",
        json={"text": "你好"},
        headers={"Authorization": "Bearer bad-token"},
    )
    assert response.status_code == 401


def test_synthesize_rejects_oversized_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_mod.settings, "max_tts_chars", 10)
    monkeypatch.setattr(settings_mod.settings, "qwen_api_key", "test-key")
    client = TestClient(_app())
    response = client.post(
        "/v1/synthesize",
        json={"text": "这是一段明显超过十个字的文本内容"},
        headers=_auth_headers(),
    )
    assert response.status_code == 413


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

    monkeypatch.setattr(settings_mod.settings, "qwen_api_key", "test-key")
    monkeypatch.setattr(tts, "httpx", FakeHttpx, raising=False)

    client = TestClient(_app())

    response = client.post(
        "/v1/synthesize",
        json={"text": "你好", "format": "mp3", "voice": "zh_female_warm"},
        headers=_auth_headers(),
    )

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


def test_synthesize_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_memory_store()
    monkeypatch.setattr(settings_mod.settings, "tts_rate_limit_per_minute", 1)
    monkeypatch.setattr(settings_mod.settings, "qwen_api_key", "test-key")

    async def fake_pcm(text: str) -> bytes:
        return b"\x01\x00"

    monkeypatch.setattr(tts, "synthesize_pcm", fake_pcm)

    client = TestClient(_app())
    headers = _auth_headers("rate-limit-user-tts")
    assert client.post("/v1/synthesize", json={"text": "一"}, headers=headers).status_code == 200
    second = client.post("/v1/synthesize", json={"text": "二"}, headers=headers)
    assert second.status_code == 429
