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
    """Enable pgvector and convert embedding column from Text to vector(1536).

    If pgvector extension is not available, this migration is a no-op —
    the Text column continues to work as a fallback.
    """
    conn = op.get_bind()

    try:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception:
        # pgvector not installed — skip, keep Text column
        return

    # Drop the old Text column and replace with vector type
    op.execute("ALTER TABLE memory_embeddings DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE memory_embeddings ADD COLUMN embedding vector(1536)")

    # HNSW index for cosine similarity search
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_embeddings_vector "
        "ON memory_embeddings USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_memory_embeddings_vector")
    op.execute("ALTER TABLE memory_embeddings DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE memory_embeddings ADD COLUMN embedding text")
