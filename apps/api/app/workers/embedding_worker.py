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
    from app.db.session import async_session
    from app.db.models import Memory, MemoryEmbedding
    from sqlalchemy import select

    async with async_session() as db:
        # Get memory content
        result = await db.execute(
            select(Memory).where(Memory.id == memory_id)
        )
        memory = result.scalar_one_or_none()
        if not memory:
            logger.warning(f"Memory not found: {memory_id}")
            return

        # Generate embedding using model
        # V1: Use OpenAI-compatible embedding API
        try:
            from openai import AsyncOpenAI
            from app.config.settings import settings

            client = AsyncOpenAI(
                api_key=settings.qwen_api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
            resp = await client.embeddings.create(
                model="text-embedding-v3",
                input=memory.content[:2000],
            )
            embedding_vector = resp.data[0].embedding

            # Store
            emb = MemoryEmbedding(
                memory_id=memory.id,
                embedding=embedding_vector,
                model="text-embedding-v3",
            )
            db.add(emb)
            await db.commit()
            logger.info(f"Embedding generated for memory {memory_id}")

        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
