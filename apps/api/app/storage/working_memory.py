from __future__ import annotations

import json
import logging
from typing import Optional

from app.storage.redis_client import get_redis

logger = logging.getLogger(__name__)

L0_MAX_MESSAGES = 20
L0_KEY_PREFIX = "wm:"
L1_KEY_PREFIX = "ss:"


async def append_message(session_id: str, role: str, content: str):
    """Append a message to L0 working memory. Evict oldest if > 20."""
    r = await get_redis()
    key = f"{L0_KEY_PREFIX}{session_id}"

    msg = json.dumps({"role": role, "content": content}, ensure_ascii=False)

    # Use a Redis list for ordered messages
    await r.rpush(key, msg)

    # Trim to max
    length = await r.llen(key)
    if length > L0_MAX_MESSAGES:
        await r.ltrim(key, length - L0_MAX_MESSAGES, -1)


async def get_working_memory(session_id: str) -> list[dict]:
    """Get all messages from L0."""
    r = await get_redis()
    key = f"{L0_KEY_PREFIX}{session_id}"
    raw_list = await r.lrange(key, 0, -1)
    messages = []
    for raw in raw_list:
        try:
            messages.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return messages


async def get_message_count(session_id: str) -> int:
    """Get current message count in L0."""
    r = await get_redis()
    key = f"{L0_KEY_PREFIX}{session_id}"
    return await r.llen(key)


async def set_session_summary(session_id: str, summary: str):
    """Set L1 session summary."""
    r = await get_redis()
    key = f"{L1_KEY_PREFIX}{session_id}"
    # Truncate to 500 chars
    await r.set(key, summary[:500])


async def get_session_summary(session_id: str) -> Optional[str]:
    """Get L1 session summary."""
    r = await get_redis()
    key = f"{L1_KEY_PREFIX}{session_id}"
    return await r.get(key)


async def clear_session_memory(session_id: str):
    """Clear both L0 and L1 for a session."""
    r = await get_redis()
    await r.delete(f"{L0_KEY_PREFIX}{session_id}")
    await r.delete(f"{L1_KEY_PREFIX}{session_id}")
