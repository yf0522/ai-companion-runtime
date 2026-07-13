"""add pgvector embedding column

Revision ID: a1b2c3d4e5f6
Revises: 392b03f56f9f
Create Date: 2026-06-13 14:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '392b03f56f9f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enable pgvector and preserve existing embeddings during conversion."""
    conn = op.get_bind()

    try:
        # PostgreSQL marks the current transaction failed after a statement
        # error. Isolate optional extension discovery in a savepoint so the
        # outer Alembic transaction remains usable when pgvector is absent.
        with conn.begin_nested():
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception as exc:
        raise RuntimeError(
            "pgvector is required; install the vector extension and grant CREATE EXTENSION "
            "permission before rerunning migration a1b2c3d4e5f6"
        ) from exc

    op.execute(
        """
        DO $migration$
        BEGIN
            ALTER TABLE memory_embeddings
            ALTER COLUMN embedding TYPE vector(1536)
            USING CASE
                WHEN embedding IS NULL THEN NULL
                ELSE embedding::vector(1536)
            END;
        EXCEPTION WHEN OTHERS THEN
            RAISE EXCEPTION USING
                MESSAGE = 'legacy memory embeddings could not be converted to vector(1536)',
                DETAIL = SQLERRM,
                HINT = 'Repair every non-null embedding as a valid 1536-dimensional pgvector literal, then rerun migration a1b2c3d4e5f6.';
        END
        $migration$
        """
    )

    # HNSW index for cosine similarity search
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_embeddings_vector "
        "ON memory_embeddings USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_memory_embeddings_vector")
    op.execute(
        "ALTER TABLE memory_embeddings "
        "ALTER COLUMN embedding TYPE text USING embedding::text"
    )
