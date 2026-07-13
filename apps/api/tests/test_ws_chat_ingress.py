from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import ws_chat
from app.api.auth import create_token
from app.runtime.websocket_gateway import Connection, WebSocketGateway


def test_web_chat_rejects_oversize_message_before_runtime(monkeypatch):
    runtime_call = AsyncMock()
    monkeypatch.setattr(ws_chat.ws_connect_limiter, "check", AsyncMock(return_value=True))
    monkeypatch.setattr(ws_chat.ws_message_limiter, "check", AsyncMock(return_value=True))
    monkeypatch.setattr(
        ws_chat.gateway,
        "connect",
        AsyncMock(return_value=SimpleNamespace(session_id="session-1", agent_runtime="harness")),
    )
    monkeypatch.setattr(ws_chat.gateway, "handle_message", runtime_call)
    monkeypatch.setattr(ws_chat.gateway, "disconnect", AsyncMock())

    app = FastAPI()
    app.include_router(ws_chat.router)
    token = create_token("4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf", "elder", role="elder")

    with TestClient(app).websocket_connect("/ws/chat") as websocket:
        websocket.send_json({"type": "auth", "token": token})
        assert websocket.receive_json()["type"] == "connected"
        websocket.send_text("x" * (ws_chat._MAX_WS_FRAME_BYTES + 1))
        error = websocket.receive_json()

    assert error == {
        "type": "error",
        "code": "frame_too_large",
        "message": "消息帧过大。",
        "retry": False,
    }
    runtime_call.assert_not_awaited()


def _client() -> tuple[TestClient, str]:
    app = FastAPI()
    app.include_router(ws_chat.router)
    token = create_token("4b2e9f4d-7e7d-4e9a-bc3e-3f3b9e1a5ddf", "elder", role="elder")
    return TestClient(app), token


def test_web_chat_rejects_array_auth_frame(monkeypatch):
    connect = AsyncMock()
    monkeypatch.setattr(ws_chat.gateway, "connect", connect)
    client, _token = _client()

    with client.websocket_connect("/ws/chat") as websocket:
        websocket.send_json([])
        error = websocket.receive_json()

    assert error["code"] == "invalid_auth_frame"
    connect.assert_not_awaited()


def test_web_chat_rejects_non_string_auth_token(monkeypatch):
    connect = AsyncMock()
    monkeypatch.setattr(ws_chat.gateway, "connect", connect)
    client, _token = _client()

    with client.websocket_connect("/ws/chat") as websocket:
        websocket.send_json({"type": "auth", "token": 42})
        error = websocket.receive_json()

    assert error["code"] == "invalid_auth_frame"
    connect.assert_not_awaited()


@pytest.mark.parametrize(
    ("frame", "code"),
    [
        ([], "invalid_frame"),
        ({"type": "user_message", "message": {"text": "hello"}}, "invalid_message"),
        ({"type": "stop_generation", "trace_id": 42}, "invalid_trace_id"),
    ],
)
def test_web_chat_rejects_malformed_message_frames(monkeypatch, frame, code):
    monkeypatch.setattr(ws_chat.ws_connect_limiter, "check", AsyncMock(return_value=True))
    monkeypatch.setattr(
        ws_chat.gateway,
        "connect",
        AsyncMock(return_value=Connection(
            websocket=MagicMock(), user_id="user-1", session_id="session-1"
        )),
    )
    monkeypatch.setattr(ws_chat.gateway, "disconnect", AsyncMock())
    client, token = _client()

    with client.websocket_connect("/ws/chat") as websocket:
        websocket.send_json({"type": "auth", "token": token})
        assert websocket.receive_json()["type"] == "connected"
        websocket.send_json(frame)
        error = websocket.receive_json()

    assert error["code"] == code


def test_stop_generation_is_consumed_while_runtime_is_in_flight(monkeypatch):
    started = threading.Event()
    cancelled = threading.Event()

    async def connect(websocket, user_id, session_id, agent_runtime):
        return Connection(
            websocket=websocket,
            user_id=user_id,
            session_id=session_id or "session-1",
            agent_runtime=agent_runtime,
        )

    async def handle(conn, _message):
        conn.is_generating = True
        conn.active_trace_id = "trace-1"
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            conn.is_generating = False
            cancelled.set()

    monkeypatch.setattr(ws_chat.ws_connect_limiter, "check", AsyncMock(return_value=True))
    monkeypatch.setattr(ws_chat.ws_message_limiter, "check", AsyncMock(return_value=True))
    monkeypatch.setattr(ws_chat.gateway, "connect", connect)
    monkeypatch.setattr(ws_chat.gateway, "handle_message", handle)
    monkeypatch.setattr(ws_chat.gateway, "disconnect", AsyncMock())
    client, token = _client()

    with client.websocket_connect("/ws/chat") as websocket:
        websocket.send_json({"type": "auth", "token": token})
        websocket.receive_json()
        websocket.send_json({"type": "user_message", "message": "hello"})
        assert started.wait(1.0)
        websocket.send_json({"type": "stop_generation", "trace_id": "trace-1"})
        assert cancelled.wait(1.0)


@pytest.mark.asyncio
async def test_gateway_stop_is_trace_bound_and_cancels_only_matching_active_task():
    gateway = WebSocketGateway()
    conn = Connection(
        websocket=MagicMock(),
        user_id="user-1",
        session_id="session-1",
        agent_runtime="pi_experimental",
        is_generating=True,
    )
    upstream_cleaned = asyncio.Event()

    async def stalled_turn():
        try:
            await asyncio.Event().wait()
        finally:
            upstream_cleaned.set()

    task = asyncio.create_task(stalled_turn())
    conn.active_message_task = task
    conn.active_trace_id = "trace-new"
    await asyncio.sleep(0)

    assert await gateway.stop_generation(conn, "trace-old") is False
    assert conn.cancel_event.is_set() is False
    assert task.done() is False

    assert await gateway.stop_generation(conn, "trace-new") is True
    assert conn.cancel_event.is_set() is True
    assert upstream_cleaned.is_set() is True
    assert task.cancelled() is True
    conn.websocket.send_json.assert_awaited_once_with(
        {"type": "cancelled", "trace_id": "trace-new"}
    )


def test_concurrent_user_turn_is_rejected_with_busy_code(monkeypatch):
    started = threading.Event()

    async def connect(websocket, user_id, session_id, agent_runtime):
        return Connection(
            websocket=websocket,
            user_id=user_id,
            session_id=session_id or "session-1",
            agent_runtime=agent_runtime,
        )

    async def handle(conn, _message):
        conn.is_generating = True
        started.set()
        await conn.cancel_event.wait()
        conn.is_generating = False

    monkeypatch.setattr(ws_chat.ws_connect_limiter, "check", AsyncMock(return_value=True))
    monkeypatch.setattr(ws_chat.ws_message_limiter, "check", AsyncMock(return_value=True))
    monkeypatch.setattr(ws_chat.gateway, "connect", connect)
    monkeypatch.setattr(ws_chat.gateway, "handle_message", handle)
    monkeypatch.setattr(ws_chat.gateway, "disconnect", AsyncMock())
    client, token = _client()

    with client.websocket_connect("/ws/chat") as websocket:
        websocket.send_json({"type": "auth", "token": token})
        websocket.receive_json()
        websocket.send_json({"type": "user_message", "message": "first"})
        assert started.wait(1.0)
        websocket.send_json({"type": "user_message", "message": "second"})
        error = websocket.receive_json()
        assert error["code"] == "turn_in_progress"
        websocket.send_json({"type": "stop_generation", "trace_id": "trace-1"})


@pytest.mark.asyncio
async def test_websocket_gateway_hides_runtime_exception_text(monkeypatch, caplog):
    secret = "sk-secret https://provider.example/private database row"

    class _Runtime:
        async def run(self, **_kwargs):
            raise RuntimeError(secret)

    monkeypatch.setattr("app.runtime.websocket_gateway.get_agent_runtime", lambda _name: _Runtime())
    monkeypatch.setattr("app.runtime.session_service.increment_message_count", AsyncMock())
    websocket = MagicMock()
    websocket.send_json = AsyncMock()
    conn = Connection(
        websocket=websocket,
        user_id="user-1",
        session_id="session-1",
        agent_runtime="harness",
    )

    await WebSocketGateway().handle_message(conn, "hello")

    payload = websocket.send_json.await_args.args[0]
    assert payload["code"] == "runtime_error"
    assert payload["message"] == "服务暂时不可用，请稍后再试。"
    assert secret not in caplog.text
