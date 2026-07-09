"""ASR HTTP endpoint auth, size limits, and rate limiting."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import asr
from app.api.auth import create_token
from app.api.rate_limiter import clear_memory_store
from app.config import settings as settings_mod


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(asr.router)
    return app


def _auth_headers(user_id: str = "4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf") -> dict[str, str]:
    token = create_token(user_id, "audio-user", role="elder")
    return {"Authorization": f"Bearer {token}"}


def test_recognize_requires_token() -> None:
    client = TestClient(_app())
    response = client.post("/v1/recognize", content=b"\x00" * 1280)
    assert response.status_code == 401


def test_recognize_rejects_invalid_token() -> None:
    client = TestClient(_app())
    response = client.post(
        "/v1/recognize",
        content=b"\x00" * 1280,
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert response.status_code == 401


def test_recognize_rejects_oversized_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_mod.settings, "max_asr_bytes", 1000)
    client = TestClient(_app())
    response = client.post(
        "/v1/recognize",
        content=b"\x00" * 1500,
        headers=_auth_headers(),
    )
    assert response.status_code == 413


def test_recognize_success_with_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_mod.settings, "qwen_api_key", "test-key")
    monkeypatch.setattr(asr, "_transcribe_sync", lambda wav_data, sample_rate: "你好")

    client = TestClient(_app())
    response = client.post(
        "/v1/recognize",
        content=b"\x00" * 1280,
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["text"] == "你好"


def test_recognize_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_memory_store()
    monkeypatch.setattr(settings_mod.settings, "asr_rate_limit_per_minute", 2)
    monkeypatch.setattr(settings_mod.settings, "qwen_api_key", "test-key")
    monkeypatch.setattr(asr, "_transcribe_sync", lambda wav_data, sample_rate: "ok")

    client = TestClient(_app())
    headers = _auth_headers("rate-limit-user-asr")
    assert client.post("/v1/recognize", content=b"\x00" * 1280, headers=headers).status_code == 200
    assert client.post("/v1/recognize", content=b"\x00" * 1280, headers=headers).status_code == 200
    third = client.post("/v1/recognize", content=b"\x00" * 1280, headers=headers)
    assert third.status_code == 429
