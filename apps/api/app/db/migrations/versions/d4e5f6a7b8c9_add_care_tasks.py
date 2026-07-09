"""add care_tasks table

Revision ID: d4e5f6a7b8c9
Revises: c2f3d1a9e7f4
Create Date: 2026-07-09 21:56:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c2f3d1a9e7f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "care_tasks",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("task_type", sa.String(), nullable=False, server_default="medication"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("snooze_until", sa.DateTime(), nullable=True),
        sa.Column("reminder_id", sa.UUID(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False, server_default="chat"),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reminder_id"], ["reminders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_care_tasks_user_status", "care_tasks", ["user_id", "status"], unique=False)
    op.create_index("idx_care_tasks_due", "care_tasks", ["due_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_care_tasks_due", table_name="care_tasks")
    op.drop_index("idx_care_tasks_user_status", table_name="care_tasks")
    op.drop_table("care_tasks")
