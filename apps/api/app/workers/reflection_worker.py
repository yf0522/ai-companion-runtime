from __future__ import annotations

import logging

from app.workers.celery_app import app
from app.workers.async_runner import run_async_task

logger = logging.getLogger(__name__)


@app.task(name="app.workers.reflection_worker.run_reflection")
def run_reflection(user_id: str, session_id: str):
    """Analyze recent conversations and propose profile changes."""
    run_async_task(lambda: _reflect(user_id, session_id))


async def _reflect(user_id: str, session_id: str):
    """V1: Simple extraction of facts from recent messages."""
    import uuid
    from app.storage.working_memory import get_working_memory
    from app.db.session import async_session
    from app.db.memory_models import ReflectionProposal
    from app.memory.lifecycle import MEMORY_POLICY_VERSION
    from sqlalchemy import select
    import re

    # Convert string user_id to UUID for DB queries
    try:
        db_user_id = uuid.UUID(user_id)
    except (ValueError, TypeError):
        logger.warning(f"Invalid user_id for reflection: {user_id}")
        return
    try:
        db_session_id = uuid.UUID(session_id)
    except (ValueError, TypeError):
        db_session_id = None

    messages = await get_working_memory(session_id)
    if not messages:
        return

    # Extract simple facts from user messages
    user_msgs = [m["content"] for m in messages if m.get("role") == "user"]
    text = " ".join(user_msgs)

    extracted = {}

    # Name extraction
    name_match = re.search(
        r"我叫([\u4e00-\u9fff·]{1,4})|我的名字(?:是|叫)([\u4e00-\u9fff·]{1,4})",
        text,
    )
    if name_match:
        extracted["name"] = name_match.group(1) or name_match.group(2)

    # Location
    loc_match = re.search(
        r"(?:我在|我住在|住在|坐标|在)([\u4e00-\u9fffA-Za-z0-9·-]{2,20})",
        text,
    )
    if loc_match:
        extracted["location"] = loc_match.group(1)

    if not extracted:
        return

    async with async_session() as db:
        existing = await db.execute(
            select(ReflectionProposal).where(
                ReflectionProposal.user_id == db_user_id,
                ReflectionProposal.session_id == db_session_id,
                ReflectionProposal.status == "proposed",
            )
        )
        proposal = existing.scalar_one_or_none()
        if proposal:
            proposal.proposed_json = extracted
            proposal.source_json = {"session_id": session_id, "source": "working_memory"}
        else:
            db.add(
                ReflectionProposal(
                    user_id=db_user_id,
                    session_id=db_session_id,
                    target_type="user_profile",
                    proposed_json=extracted,
                    source_json={"session_id": session_id, "source": "working_memory"},
                    policy_version=MEMORY_POLICY_VERSION,
                    status="proposed",
                )
            )

        await db.commit()
        logger.info(f"Profile reflection proposed for user {user_id}: {extracted}")


@app.task(name="app.workers.reflection_worker.generate_session_summary")
def generate_session_summary(session_id: str):
    """Generate final summary when session ends."""
    from app.workers.memory_worker import update_session_summary
    update_session_summary(session_id)


@app.task(name="app.workers.reflection_worker.accept_reflection_proposal")
def accept_reflection_proposal(proposal_id: str, accepted_by: str):
    run_async_task(lambda: _accept_reflection_proposal(proposal_id, accepted_by))


async def _accept_reflection_proposal(proposal_id: str, accepted_by: str) -> bool:
    import uuid
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.db.memory_models import ReflectionProposal
    from app.db.models import UserProfileModel
    from app.db.session import async_session

    try:
        db_proposal_id = uuid.UUID(proposal_id)
        db_accepted_by = uuid.UUID(accepted_by)
    except (ValueError, TypeError):
        logger.warning("Invalid proposal acceptance ids")
        return False

    async with async_session() as db:
        result = await db.execute(
            select(ReflectionProposal).where(
                ReflectionProposal.id == db_proposal_id,
                ReflectionProposal.user_id == db_accepted_by,
                ReflectionProposal.status == "proposed",
            )
        )
        proposal = result.scalar_one_or_none()
        if (
            not proposal
            or proposal.user_id != db_accepted_by
            or proposal.target_type != "user_profile"
        ):
            return False

        profile_result = await db.execute(
            select(UserProfileModel).where(UserProfileModel.user_id == proposal.user_id)
        )
        profile = profile_result.scalar_one_or_none()
        if profile:
            current = profile.profile_json or {}
            current.update(proposal.proposed_json)
            profile.profile_json = current
            profile.version += 1
        else:
            db.add(UserProfileModel(user_id=proposal.user_id, profile_json=proposal.proposed_json))

        proposal.status = "accepted"
        proposal.accepted_by = db_accepted_by
        proposal.accepted_at = datetime.now(UTC).replace(tzinfo=None)
        await db.commit()
        return True
