"""add memory lifecycle metadata

Revision ID: b8c9d0e1f2a3
Revises: d4e5f6a7b8c9
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("memories", sa.Column("source", sa.String(), nullable=False, server_default="chat"))
    op.add_column("memories", sa.Column("source_trace_id", sa.String(), nullable=True))
    op.add_column("memories", sa.Column("source_actor", sa.String(), nullable=True))
    op.add_column(
        "memories",
        sa.Column("purpose", sa.String(), nullable=False, server_default="care_continuity"),
    )
    op.add_column(
        "memories",
        sa.Column("sensitivity", sa.String(), nullable=False, server_default="general"),
    )
    op.add_column("memories", sa.Column("retention_until", sa.DateTime(), nullable=True))
    op.add_column("memories", sa.Column("consent_grant_id", sa.UUID(), nullable=True))
    op.add_column(
        "memories",
        sa.Column("consent_status", sa.String(), nullable=False, server_default="legacy_unverified"),
    )
    op.add_column(
        "memories",
        sa.Column("extraction_model", sa.String(), nullable=False, server_default="rule_importance"),
    )
    op.add_column(
        "memories",
        sa.Column("extraction_model_version", sa.String(), nullable=False, server_default="2026-07-10"),
    )
    op.add_column(
        "memories",
        sa.Column("correction_state", sa.String(), nullable=False, server_default="original"),
    )
    op.add_column(
        "memories",
        sa.Column("deletion_state", sa.String(), nullable=False, server_default="active"),
    )
    op.add_column("memories", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.add_column(
        "memories",
        sa.Column("embedding_state", sa.String(), nullable=False, server_default="pending"),
    )
    op.add_column("memories", sa.Column("embedding_model", sa.String(), nullable=True))
    op.add_column("memories", sa.Column("embedding_model_version", sa.String(), nullable=True))
    op.add_column("memories", sa.Column("embedding_deleted_at", sa.DateTime(), nullable=True))
    op.create_index(
        "idx_memories_lifecycle_retrieval",
        "memories",
        ["user_id", "purpose", "consent_status", "deletion_state", "retention_until"],
    )

    op.add_column("memory_embeddings", sa.Column("model_version", sa.String(), nullable=True))
    op.add_column(
        "memory_embeddings",
        sa.Column("state", sa.String(), nullable=False, server_default="active"),
    )
    op.add_column("memory_embeddings", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.create_index("idx_memory_embeddings_state", "memory_embeddings", ["state", "deleted_at"])

    op.create_table(
        "memory_consent_grants",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("granted_by", sa.UUID(), nullable=True),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column(
            "scope_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "sensitivity_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("consent_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("granted_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_memory_consent_user_purpose",
        "memory_consent_grants",
        ["user_id", "purpose", "status"],
    )
    op.create_foreign_key(
        "fk_memories_consent_grant",
        "memories",
        "memory_consent_grants",
        ["consent_grant_id"],
        ["id"],
        use_alter=True,
    )
    op.create_table(
        "memory_correction_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("memory_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("original_content", sa.Text(), nullable=False),
        sa.Column("corrected_content", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("applied_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_memory_correction_memory", "memory_correction_events", ["memory_id", "created_at"])
    op.create_table(
        "memory_reflection_proposals",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("proposed_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "source_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("accepted_by", sa.UUID(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["accepted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_memory_reflection_user_status",
        "memory_reflection_proposals",
        ["user_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_memory_reflection_user_status", table_name="memory_reflection_proposals")
    op.drop_table("memory_reflection_proposals")
    op.drop_index("idx_memory_correction_memory", table_name="memory_correction_events")
    op.drop_table("memory_correction_events")
    op.drop_constraint("fk_memories_consent_grant", "memories", type_="foreignkey")
    op.drop_index("idx_memory_consent_user_purpose", table_name="memory_consent_grants")
    op.drop_table("memory_consent_grants")
    op.drop_index("idx_memory_embeddings_state", table_name="memory_embeddings")
    op.drop_column("memory_embeddings", "deleted_at")
    op.drop_column("memory_embeddings", "state")
    op.drop_column("memory_embeddings", "model_version")
    op.drop_index("idx_memories_lifecycle_retrieval", table_name="memories")
    for column in (
        "embedding_deleted_at",
        "embedding_model_version",
        "embedding_model",
        "embedding_state",
        "deleted_at",
        "deletion_state",
        "correction_state",
        "extraction_model_version",
        "extraction_model",
        "consent_status",
        "consent_grant_id",
        "retention_until",
        "sensitivity",
        "purpose",
        "source_actor",
        "source_trace_id",
        "source",
    ):
        op.drop_column("memories", column)
