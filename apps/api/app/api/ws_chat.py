import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.auth import decode_token
from app.api.rate_limiter import ws_connect_limiter, ws_message_limiter
from app.runtime.websocket_gateway import WebSocketGateway

logger = logging.getLogger(__name__)
router = APIRouter()
gateway = WebSocketGateway()

# Max seconds to wait for the client to send an auth message after connect
_AUTH_TIMEOUT_S = 10


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()

    # --- Phase 1: First-message authentication ---
    # Client must send {"type": "auth", "token": "<JWT>"} as its first message.
    # This avoids putting the long-lived JWT in the URL query string where it
    # leaks into browser history, proxy logs, and server access logs.
    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(), timeout=_AUTH_TIMEOUT_S,
        )
        data = json.loads(raw)
    except asyncio.TimeoutError:
        await websocket.send_json({
            "type": "error", "code": "auth_timeout",
            "message": "Auth message not received in time", "retry": False,
        })
        await websocket.close(code=4001, reason="Auth timeout")
        return
    except Exception:
        await websocket.send_json({
            "type": "error", "code": "invalid_json",
            "message": "First message must be valid JSON", "retry": False,
        })
        await websocket.close(code=4001, reason="Bad auth message")
        return

    if data.get("type") != "auth" or not data.get("token"):
        await websocket.send_json({
            "type": "error", "code": "auth_required",
            "message": 'First message must be {"type":"auth","token":"<JWT>"}',
            "retry": False,
        })
        await websocket.close(code=4001, reason="Auth required")
        return

    payload = decode_token(data["token"])
    if not payload or "sub" not in payload:
        await websocket.send_json({
            "type": "error", "code": "auth_failed",
            "message": "Invalid or expired token", "retry": False,
        })
        await websocket.close(code=4001, reason="Unauthorized")
        return

    user_id = payload["sub"]
    session_id = data.get("session_id")

    # Family accounts receive risk summaries / confirmation tasks only —
    # they must not open the elder's private chat WebSocket.
    if payload.get("role") == "family":
        await websocket.send_json({
            "type": "error",
            "code": "family_chat_forbidden",
            "message": "家属账号只能查看通知与提醒确认，不能进入老人私聊",
            "retry": False,
        })
        await websocket.close(code=4003, reason="Family chat forbidden")
        return

    # --- Phase 2: Rate-limit connections ---
    connect_allowed = await ws_connect_limiter.check(f"ws_connect:{user_id}")
    if not connect_allowed:
        await websocket.send_json({
            "type": "error", "code": "rate_limited",
            "message": "Too many connections. Please try again later.",
            "retry": True,
        })
        await websocket.close(code=4029, reason="Rate limited")
        return

    # --- Phase 3: Establish connection ---
    try:
        conn = await gateway.connect(websocket, user_id, session_id)
    except RuntimeError as e:
        await websocket.send_json({
            "type": "error", "code": "session_error",
            "message": "Failed to create session. Please try again.",
            "retry": True,
        })
        await websocket.close(code=4500, reason="Session creation failed")
        return

    try:
        await websocket.send_json({
            "type": "connected",
            "session_id": conn.session_id,
        })

        # --- Phase 4: Message loop ---
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error", "code": "invalid_json",
                    "message": "Invalid JSON", "retry": False,
                })
                continue

            msg_type = data.get("type", "")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "user_message":
                message = data.get("message", "").strip()
                if not message:
                    await websocket.send_json({
                        "type": "error", "code": "empty_message",
                        "message": "Message is empty", "retry": False,
                    })
                    continue
                # Rate limit messages per user
                msg_allowed = await ws_message_limiter.check(f"ws_msg:{user_id}")
                if not msg_allowed:
                    await websocket.send_json({
                        "type": "error", "code": "rate_limited",
                        "message": "Sending too fast, please slow down.",
                        "retry": True,
                    })
                    continue
                await gateway.handle_message(conn, message)

            elif msg_type == "stop_generation":
                trace_id = data.get("trace_id", "")
                await gateway.stop_generation(conn, trace_id)

            else:
                await websocket.send_json({
                    "type": "error", "code": "unknown_type",
                    "message": f"Unknown message type: {msg_type}",
                    "retry": False,
                })

    except WebSocketDisconnect:
        logger.info(f"Client disconnected: user={user_id} session={conn.session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        await gateway.disconnect(conn)
