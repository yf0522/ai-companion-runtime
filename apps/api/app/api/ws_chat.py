import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.runtime.websocket_gateway import WebSocketGateway

logger = logging.getLogger(__name__)
router = APIRouter()
gateway = WebSocketGateway()


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()

    # Extract token from query params (JWT validation will be Phase 6)
    token = websocket.query_params.get("token", "")
    session_id = websocket.query_params.get("session_id")
    last_msg_id = websocket.query_params.get("last_msg_id")

    # For now, use a placeholder user_id (JWT decode in Phase 6)
    user_id = "u_default"

    conn = await gateway.connect(websocket, user_id, session_id)

    try:
        # Send connected message
        await websocket.send_json({
            "type": "connected",
            "session_id": conn.session_id,
        })

        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "code": "invalid_json", "message": "Invalid JSON", "retry": False})
                continue

            msg_type = data.get("type", "")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "user_message":
                message = data.get("message", "").strip()
                if not message:
                    await websocket.send_json({"type": "error", "code": "empty_message", "message": "Message is empty", "retry": False})
                    continue
                await gateway.handle_message(conn, message)

            elif msg_type == "stop_generation":
                trace_id = data.get("trace_id", "")
                await gateway.stop_generation(conn, trace_id)

            else:
                await websocket.send_json({"type": "error", "code": "unknown_type", "message": f"Unknown message type: {msg_type}", "retry": False})

    except WebSocketDisconnect:
        logger.info(f"Client disconnected: user={user_id} session={conn.session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        await gateway.disconnect(conn)
