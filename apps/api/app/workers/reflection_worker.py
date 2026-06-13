from __future__ import annotations

import logging

from app.workers.celery_app import app

logger = logging.getLogger(__name__)


@app.task(name="app.workers.reflection_worker.run_reflection")
def run_reflection(user_id: str, session_id: str):
    """Analyze recent conversations and update user profile."""
    import asyncio
    asyncio.run(_reflect(user_id, session_id))


async def _reflect(user_id: str, session_id: str):
    """V1: Simple extraction of facts from recent messages."""
    import uuid
    from app.storage.working_memory import get_working_memory
    from app.db.session import async_session
    from app.db.models import UserProfileModel
    from sqlalchemy import select
    import re

    # Convert string user_id to UUID for DB queries
    try:
        db_user_id = uuid.UUID(user_id)
    except (ValueError, TypeError):
        logger.warning(f"Invalid user_id for reflection: {user_id}")
        return

    messages = await get_working_memory(session_id)
    if not messages:
        return

    # Extract simple facts from user messages
    user_msgs = [m["content"] for m in messages if m.get("role") == "user"]
    text = " ".join(user_msgs)

    extracted = {}

    # Name extraction
    name_match = re.search(r"我叫(\S{1,4})|我的名字(?:是|叫)(\S{1,4})", text)
    if name_match:
        extracted["name"] = name_match.group(1) or name_match.group(2)

    # Location
    loc_match = re.search(r"(?:我在|我住在|住在|坐标|在)(\S{2,6})", text)
    if loc_match:
        extracted["location"] = loc_match.group(1)

    if not extracted:
        return

    # Update profile
    async with async_session() as db:
        result = await db.execute(
            select(UserProfileModel).where(UserProfileModel.user_id == db_user_id)
        )
        profile = result.scalar_one_or_none()

        if profile:
            current = profile.profile_json or {}
            current.update(extracted)
            profile.profile_json = current
            profile.version += 1
        else:
            profile = UserProfileModel(
                user_id=db_user_id,
                profile_json=extracted,
            )
            db.add(profile)

        await db.commit()
        logger.info(f"Profile updated for user {user_id}: {extracted}")


@app.task(name="app.workers.reflection_worker.generate_session_summary")
def generate_session_summary(session_id: str):
    """Generate final summary when session ends."""
    from app.workers.memory_worker import update_session_summary
    update_session_summary(session_id)
