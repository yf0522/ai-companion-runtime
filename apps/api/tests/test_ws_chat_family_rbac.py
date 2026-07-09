"""Family role must not open elder private chat WebSocket."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import create_token
from app.api import ws_chat


def test_family_role_rejected_from_elder_chat_ws(monkeypatch):
    # Avoid real gateway/session side effects if somehow reached
    async def boom(*_a, **_k):
        raise AssertionError("gateway.connect should not be called for family")

    monkeypatch.setattr(ws_chat.gateway, "connect", boom)

    app = FastAPI()
    app.include_router(ws_chat.router)
    client = TestClient(app)

    token = create_token(
        "4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf",
        "family-user",
        role="family",
    )

    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "auth", "token": token})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "family_chat_forbidden"
