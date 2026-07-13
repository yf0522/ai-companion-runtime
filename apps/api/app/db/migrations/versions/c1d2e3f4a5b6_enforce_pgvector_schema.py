"""enforce pgvector extension and embedding schema

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
"""

from collections.abc import Sequence

from alembic import op

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
    op.execute(
        """
        DO $migration$
        DECLARE
            current_type text;
        BEGIN
            SELECT format_type(attribute.atttypid, attribute.atttypmod)
            INTO current_type
            FROM pg_attribute AS attribute
            WHERE attribute.attrelid = to_regclass('memory_embeddings')
              AND attribute.attname = 'embedding'
              AND NOT attribute.attisdropped;

            IF current_type IS NULL THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'memory_embeddings.embedding is missing',
                    HINT = 'Restore the expected memory_embeddings schema before rerunning the migration.';
            END IF;

            IF current_type <> 'vector(1536)' THEN
                BEGIN
                    ALTER TABLE memory_embeddings
                    ALTER COLUMN embedding TYPE vector(1536)
                    USING CASE
                        WHEN embedding IS NULL THEN NULL
                        ELSE embedding::vector(1536)
                    END;
                EXCEPTION WHEN OTHERS THEN
                    RAISE EXCEPTION USING
                        MESSAGE = 'memory_embeddings.embedding could not be converted to vector(1536)',
                        DETAIL = SQLERRM,
                        HINT = 'Repair non-null embeddings so every value is a valid 1536-dimensional pgvector literal, then rerun the migration.';
                END;
            END IF;
        END
        $migration$
        """
    )
    op.execute("DROP INDEX IF EXISTS idx_memory_embeddings_vector")
    op.execute(
        "CREATE INDEX idx_memory_embeddings_vector "
        "ON memory_embeddings USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    """Preserve the vector schema already established by revision b0's ancestry."""
