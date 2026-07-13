from __future__ import annotations

import logging

from app.workers.celery_app import app
from app.workers.async_runner import run_async_task

logger = logging.getLogger(__name__)


@app.task(name="app.workers.memory_worker.append_working_memory")
def append_working_memory(session_id: str, role: str, content: str):
    """Sync wrapper for appending to L0. Called from async context via .delay()"""
    from app.storage.working_memory import append_message
    run_async_task(lambda: append_message(session_id, role, content))


@app.task(name="app.workers.memory_worker.update_session_summary")
def update_session_summary(session_id: str):
    """Compress L0 into L1 summary using lightweight model."""
    run_async_task(lambda: _update_summary(session_id))


async def _update_summary(session_id: str):
    from app.storage.working_memory import get_working_memory, set_session_summary
    messages = await get_working_memory(session_id)
    if not messages:
        return

    # Keep summaries deterministic and bounded; model-generated summaries require
    # a separate reviewed privacy policy before they can enter this lifecycle.
    parts = []
    for msg in messages[-10:]:
        role = "用户" if msg.get("role") == "user" else "AI"
        parts.append(f"{role}: {msg.get('content', '')[:50]}")

    summary = "会话摘要：" + " | ".join(parts)
    await set_session_summary(session_id, summary[:500])
    logger.info(f"Session summary updated: {session_id}")


@app.task(name="app.workers.memory_worker.evaluate_importance")
def evaluate_importance(user_id: str, content: str, session_id: str = ""):
    """Evaluate memory importance and store if >= 0.6."""
    run_async_task(lambda: _evaluate_and_store(user_id, content, session_id))


IMPORTANT_PATTERNS: list[tuple[str, float]] = [
    (r"我叫|我的名字", 0.3),
    (r"生日|纪念日", 0.3),
    (r"家人|爸爸|妈妈|老公|老婆|孩子|女朋友|男朋友", 0.25),
    (r"工作|公司|职业|辞职|入职", 0.2),
    (r"搬家|搬到|住在", 0.2),
    (r"喜欢|讨厌|最爱|害怕", 0.15),
    # Eldercare-critical facts
    (r"降压药|胰岛素|二甲双胍|吃药|用药|药物", 0.35),
    (r"医院|医生|挂号|复诊|体检|预约", 0.3),
    (r"紧急联系人|儿子|女儿|孙子|孙女", 0.25),
    (r"诈骗|骗子|验证码|转账|可疑电话|可疑来电", 0.35),
    (r"高血压|糖尿病|心脏病|头晕|胸口疼|慢性", 0.3),
]


def score_importance(content: str) -> float:
    """Rule-based importance scoring for memory storage threshold."""
    import re

    score = 0.3
    for pattern, boost in IMPORTANT_PATTERNS:
        if re.search(pattern, content):
            score += boost
    return min(1.0, score)


async def _evaluate_and_store(user_id: str, content: str, session_id: str):
    import uuid

    score = score_importance(content)

    if score >= 0.6:
        # Convert string IDs to UUID for DB insertion
        try:
            db_user_id = uuid.UUID(user_id)
        except (ValueError, TypeError):
            db_user_id = uuid.uuid5(uuid.NAMESPACE_DNS, str(user_id))

        db_session_id = None
        if session_id:
            try:
                db_session_id = uuid.UUID(session_id)
            except (ValueError, TypeError):
                db_session_id = uuid.uuid5(uuid.NAMESPACE_DNS, str(session_id))

        from app.config.settings import settings
        from app.db.session import async_session
        from app.memory.lifecycle import consent_status_for_environment, store_memory
        async with async_session() as db:
            memory_id = await store_memory(
                db,
                user_id=db_user_id,
                session_id=db_session_id,
                content=content[:500],
                importance_score=score,
                source="chat",
                source_actor="elder",
                consent_status=consent_status_for_environment(settings.app_env),
            )
            await db.commit()
            logger.info(f"Memory stored: score={score:.2f}, content={content[:50]}")

            try:
                if settings.enable_celery_tasks:
                    from app.workers.embedding_worker import generate_embedding
                    generate_embedding.delay(str(memory_id))
            except Exception as e:
                logger.debug(f"Embedding enqueue skipped: {e}")
