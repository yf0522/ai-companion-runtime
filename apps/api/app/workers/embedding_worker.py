from __future__ import annotations

import logging

from app.workers.celery_app import app

logger = logging.getLogger(__name__)


@app.task(name="app.workers.embedding_worker.generate_embedding")
def generate_embedding(memory_id: str):
    """Generate embedding for a memory and store in memory_embeddings table."""
    import asyncio
    asyncio.run(_generate(memory_id))


async def _generate(memory_id: str):
    import uuid

    from sqlalchemy import insert, select, update

    from app.config.settings import settings
    from app.db.session import async_session
    from app.memory.lifecycle import (
        DEFAULT_EMBEDDING_MODEL,
        DEFAULT_EMBEDDING_MODEL_VERSION,
        is_retrievable_memory,
        memories_table,
        memory_embeddings_table,
    )

    try:
        db_memory_id = uuid.UUID(memory_id)
    except ValueError:
        logger.warning(f"Invalid memory id for embedding: {memory_id}")
        return

    async with async_session() as db:
        memories = memories_table()
        embeddings = memory_embeddings_table()
        result = await db.execute(
            select(memories).where(memories.c.id == db_memory_id)
        )
        row = result.first()
        if not row:
            logger.warning(f"Memory not found: {memory_id}")
            return
        memory = row._mapping
        if not is_retrievable_memory(memory):
            await db.execute(
                update(memories)
                .where(memories.c.id == db_memory_id)
                .values(embedding_state="blocked_by_lifecycle")
            )
            await db.commit()
            logger.info(f"Embedding blocked by memory lifecycle: {memory_id}")
            return
        if not settings.qwen_api_key:
            await db.execute(
                update(memories)
                .where(memories.c.id == db_memory_id)
                .values(embedding_state="provider_unconfigured")
            )
            await db.commit()
            logger.warning("Embedding provider unconfigured; memory embedding left pending evidence")
            return

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=settings.qwen_api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
            resp = await client.embeddings.create(
                model=DEFAULT_EMBEDDING_MODEL,
                input=str(memory["content"])[:2000],
            )
            embedding_vector = resp.data[0].embedding

            existing = await db.execute(
                select(embeddings.c.id).where(embeddings.c.memory_id == db_memory_id)
            )
            existing_id = existing.scalar_one_or_none()
            if existing_id:
                await db.execute(
                    update(embeddings)
                    .where(embeddings.c.id == existing_id)
                    .values(
                        embedding=embedding_vector,
                        model=DEFAULT_EMBEDDING_MODEL,
                        model_version=DEFAULT_EMBEDDING_MODEL_VERSION,
                        state="active",
                        deleted_at=None,
                    )
                )
            else:
                await db.execute(
                    insert(embeddings).values(
                        memory_id=db_memory_id,
                        embedding=embedding_vector,
                        model=DEFAULT_EMBEDDING_MODEL,
                        model_version=DEFAULT_EMBEDDING_MODEL_VERSION,
                        state="active",
                    )
                )
            await db.execute(
                update(memories)
                .where(memories.c.id == db_memory_id)
                .values(
                    embedding_state="active",
                    embedding_model=DEFAULT_EMBEDDING_MODEL,
                    embedding_model_version=DEFAULT_EMBEDDING_MODEL_VERSION,
                    embedding_deleted_at=None,
                )
            )
            await db.commit()
            logger.info(f"Embedding generated for memory {memory_id}")

        except Exception as e:
            await db.execute(
                update(memories)
                .where(memories.c.id == db_memory_id)
                .values(embedding_state="failed")
            )
            await db.commit()
            logger.error(f"Embedding generation failed: {e}")


@app.task(name="app.workers.embedding_worker.backfill_embeddings")
def backfill_embeddings(limit: int = 100):
    import asyncio

    asyncio.run(_backfill(limit))


async def _backfill(limit: int):
    from sqlalchemy import select

    from app.db.session import async_session
    from app.memory.lifecycle import memories_table

    async with async_session() as db:
        memories = memories_table()
        result = await db.execute(
            select(memories.c.id)
            .where(
                memories.c.embedding_state.in_(
                    ["pending", "failed", "provider_unconfigured", "blocked_by_lifecycle"]
                )
            )
            .order_by(memories.c.created_at.asc())
            .limit(limit)
        )
        memory_ids = [str(row[0]) for row in result.fetchall()]

    for queued_memory_id in memory_ids:
        generate_embedding.delay(queued_memory_id)
