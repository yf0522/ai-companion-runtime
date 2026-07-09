"""add eldercare reminders and notifications

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-07-09 15:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(), server_default="elder", nullable=False),
    )

    op.create_table(
        "reminders",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("schedule_type", sa.String(), nullable=False),
        sa.Column("schedule_cron", sa.String(), nullable=True),
        sa.Column("time_of_day", sa.DateTime(), nullable=True),
        sa.Column("next_fire_at", sa.DateTime(), nullable=False),
        sa.Column("last_fired_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(), nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_reminders_user", "reminders", ["user_id"], unique=False)
    op.create_index(
        "idx_reminders_next_fire",
        "reminders",
        ["next_fire_at"],
        unique=False,
        postgresql_where=sa.text("is_active = true"),
    )

    op.create_table(
        "reminder_history",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("reminder_id", sa.UUID(), nullable=False),
        sa.Column("fired_at", sa.DateTime(), nullable=False),
        sa.Column("delivered", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("acknowledged", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["reminder_id"], ["reminders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "emergency_contacts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("relation", sa.String(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "notify_on_levels",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{critical,high}'::text[]"),
            nullable=True,
        ),
        sa.Column("webhook_url", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_emergency_contacts_user", "emergency_contacts", ["user_id"], unique=False)

    op.create_table(
        "family_bindings",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("family_user_id", sa.UUID(), nullable=False),
        sa.Column("elder_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "permissions",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{view_reminders,manage_reminders,view_notifications}'::text[]"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["family_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["elder_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_family_bindings_unique",
        "family_bindings",
        ["family_user_id", "elder_user_id"],
        unique=True,
    )

    op.create_table(
        "notification_log",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("contact_id", sa.UUID(), nullable=True),
        sa.Column("risk_level", sa.String(), nullable=False),
        sa.Column("risk_category", sa.String(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("webhook_status", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["emergency_contacts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_notification_log_user", "notification_log", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_notification_log_user", table_name="notification_log")
    op.drop_table("notification_log")
    op.drop_index("idx_family_bindings_unique", table_name="family_bindings")
    op.drop_table("family_bindings")
    op.drop_index("idx_emergency_contacts_user", table_name="emergency_contacts")
    op.drop_table("emergency_contacts")
    op.drop_table("reminder_history")
    op.drop_index("idx_reminders_next_fire", table_name="reminders")
    op.drop_index("idx_reminders_user", table_name="reminders")
    op.drop_table("reminders")
    op.drop_column("users", "role")
