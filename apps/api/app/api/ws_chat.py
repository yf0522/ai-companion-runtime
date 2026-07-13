import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.auth import decode_token
from app.api.rate_limiter import ws_connect_limiter, ws_message_limiter
from app.runtime.agent_runtime import normalize_runtime_name
from app.runtime.websocket_gateway import WebSocketGateway

logger = logging.getLogger(__name__)
router = APIRouter()
gateway = WebSocketGateway()

# Max seconds to wait for the client to send an auth message after connect
_AUTH_TIMEOUT_S = 10
_MAX_CHAT_MESSAGE_BYTES = 16 * 1024
_MAX_WS_FRAME_BYTES = 16 * 1024


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
        if len(raw.encode("utf-8")) > _MAX_WS_FRAME_BYTES:
            await websocket.send_json({
                "type": "error", "code": "frame_too_large",
                "message": "消息帧过大。", "retry": False,
            })
            await websocket.close(code=4009, reason="Frame too large")
            return
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

    if not isinstance(data, dict):
        await websocket.send_json({
            "type": "error", "code": "invalid_auth_frame",
            "message": "认证消息格式无效。", "retry": False,
        })
        await websocket.close(code=4001, reason="Invalid auth frame")
        return

    token = data.get("token")
    session_value = data.get("session_id")
    runtime_value = data.get("agent_runtime", data.get("runtime"))
    if (
        data.get("type") != "auth"
        or not isinstance(token, str)
        or not token.strip()
        or (session_value is not None and not isinstance(session_value, str))
        or (runtime_value is not None and not isinstance(runtime_value, str))
    ):
        await websocket.send_json({
            "type": "error", "code": "invalid_auth_frame",
            "message": "认证消息格式无效。",
            "retry": False,
        })
        await websocket.close(code=4001, reason="Auth required")
        return

    payload = decode_token(token)
    if not payload or "sub" not in payload:
        await websocket.send_json({
            "type": "error", "code": "auth_failed",
            "message": "Invalid or expired token", "retry": False,
        })
        await websocket.close(code=4001, reason="Unauthorized")
        return

    user_id = payload["sub"]
    session_id = session_value

    try:
        agent_runtime = normalize_runtime_name(
            runtime_value
        )
    except ValueError:
        await websocket.send_json({
            "type": "error",
            "code": "invalid_runtime",
            "message": "不支持的运行模式。",
            "retry": False,
        })
        await websocket.close(code=4002, reason="Invalid agent runtime")
        return

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
    active_message_task: asyncio.Task | None = None
    try:
        conn = await gateway.connect(
            websocket, user_id, session_id, agent_runtime=agent_runtime
        )
    except RuntimeError:
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
            "agent_runtime": conn.agent_runtime,
        })

        # --- Phase 4: Message loop ---
        while True:
            raw = await websocket.receive_text()
            if len(raw.encode("utf-8")) > _MAX_WS_FRAME_BYTES:
                await websocket.send_json({
                    "type": "error", "code": "frame_too_large",
                    "message": "消息帧过大。", "retry": False,
                })
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error", "code": "invalid_json",
                    "message": "Invalid JSON", "retry": False,
                })
                continue

            if not isinstance(data, dict):
                await websocket.send_json({
                    "type": "error", "code": "invalid_frame",
                    "message": "消息格式无效。", "retry": False,
                })
                continue

            if active_message_task is not None and active_message_task.done():
                await asyncio.gather(active_message_task, return_exceptions=True)
                active_message_task = None

            msg_type = data.get("type", "")
            if not isinstance(msg_type, str):
                await websocket.send_json({
                    "type": "error", "code": "invalid_type",
                    "message": "消息类型无效。", "retry": False,
                })
                continue

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "user_message":
                raw_message = data.get("message")
                if not isinstance(raw_message, str):
                    await websocket.send_json({
                        "type": "error", "code": "invalid_message",
                        "message": "消息内容必须是文本。", "retry": False,
                    })
                    continue
                message = raw_message.strip()
                if not message:
                    await websocket.send_json({
                        "type": "error", "code": "empty_message",
                        "message": "Message is empty", "retry": False,
                    })
                    continue
                if active_message_task is not None:
                    await websocket.send_json({
                        "type": "error", "code": "turn_in_progress",
                        "message": "上一条消息仍在处理中。", "retry": True,
                    })
                    continue
                if len(message.encode("utf-8")) > _MAX_CHAT_MESSAGE_BYTES:
                    await websocket.send_json({
                        "type": "error",
                        "code": "message_too_large",
                        "message": "消息太长，请缩短后再发送。",
                        "retry": False,
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
                conn.cancel_event.clear()
                conn.is_generating = True
                active_message_task = asyncio.create_task(
                    gateway.handle_message(conn, message)
                )
                conn.active_message_task = active_message_task

            elif msg_type == "stop_generation":
                trace_id = data.get("trace_id")
                if not isinstance(trace_id, str) or not trace_id.strip():
                    await websocket.send_json({
                        "type": "error", "code": "invalid_trace_id",
                        "message": "停止请求缺少有效标识。", "retry": False,
                    })
                    continue
                stopped = await gateway.stop_generation(conn, trace_id)
                if not stopped:
                    await websocket.send_json({
                        "type": "error",
                        "code": "trace_not_active",
                        "message": "这条回复已经结束或标识不匹配。",
                        "retry": False,
                    })

            else:
                await websocket.send_json({
                    "type": "error", "code": "unknown_type",
                    "message": "不支持的消息类型。",
                    "retry": False,
                })

    except WebSocketDisconnect:
        logger.info(f"Client disconnected: user={user_id} session={conn.session_id}")
    except Exception as exc:
        logger.error(
            "WebSocket session failed error_class=%s code=websocket_session_failed",
            type(exc).__name__,
        )
    finally:
        if active_message_task is not None:
            conn.cancel_event.set()
            if not active_message_task.done():
                active_message_task.cancel()
            await asyncio.gather(active_message_task, return_exceptions=True)
        await gateway.disconnect(conn)
