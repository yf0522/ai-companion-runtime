"""enforce pgvector extension and embedding schema

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "c1d2e3f4a5b6"
down_revision: str | None = "b0c1d2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $migration$
        BEGIN
            CREATE EXTENSION IF NOT EXISTS vector;
        EXCEPTION WHEN OTHERS THEN
            RAISE EXCEPTION USING
                MESSAGE = 'pgvector is required but the vector extension could not be enabled',
                DETAIL = SQLERRM,
                HINT = 'Install pgvector and grant this migration role permission to CREATE EXTENSION, then rerun the migration.';
        END
        $migration$
        """
    )
    bind = op.get_bind()
    current_type = bind.execute(
        text(
            """
            SELECT format_type(attribute.atttypid, attribute.atttypmod)
            FROM pg_attribute AS attribute
            WHERE attribute.attrelid = to_regclass('memory_embeddings')
              AND attribute.attname = 'embedding'
              AND NOT attribute.attisdropped
            """
        )
    ).scalar_one_or_none()
    if current_type != "vector(1536)":
        raise RuntimeError(
            "memory_embeddings.embedding is not vector(1536); run the reviewed "
            "maintenance migration with a rehearsed rewrite window before retrying"
        )

    index_definition = bind.execute(
        text(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = current_schema()
              AND indexname = 'idx_memory_embeddings_vector'
            """
        )
    ).scalar_one_or_none()
    if "using hnsw (embedding vector_cosine_ops)" in (index_definition or "").lower():
        return

    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_memory_embeddings_vector_replacement")
        op.execute(
            "CREATE INDEX CONCURRENTLY idx_memory_embeddings_vector_replacement "
            "ON memory_embeddings USING hnsw (embedding vector_cosine_ops)"
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_memory_embeddings_vector")
        op.execute(
            "ALTER INDEX idx_memory_embeddings_vector_replacement "
            "RENAME TO idx_memory_embeddings_vector"
        )


def downgrade() -> None:
    """No-op: preserve b0's forward-compatible vector schema and production data."""
