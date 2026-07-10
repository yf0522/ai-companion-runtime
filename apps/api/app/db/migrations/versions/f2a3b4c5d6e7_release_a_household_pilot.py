"""release a household pilot domain

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-10 07:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "households",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("elder_user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["elder_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("elder_user_id", name="uq_households_elder"),
    )
    op.create_index("idx_households_elder", "households", ["elder_user_id"], unique=False)

    op.create_table(
        "care_circle_members",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column("permissions", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "user_id", name="uq_care_circle_household_user"),
    )
    op.create_index("idx_care_circle_members_user", "care_circle_members", ["user_id", "status"], unique=False)

    op.create_table(
        "household_invites",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("elder_user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("invitee_email", sa.String(), nullable=True),
        sa.Column(
            "permissions",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{view_reminders,manage_reminders,view_notifications}'::text[]"),
            nullable=True,
        ),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("accepted_by_user_id", sa.UUID(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("denied_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("replay_nonce", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.ForeignKeyConstraint(["elder_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_household_invites_token_hash"),
    )
    op.create_index(
        "idx_household_invites_household_status",
        "household_invites",
        ["household_id", "status"],
        unique=False,
    )

    op.add_column("family_bindings", sa.Column("household_id", sa.UUID(), nullable=True))
    op.add_column("family_bindings", sa.Column("status", sa.String(), server_default="active", nullable=False))
    op.add_column("family_bindings", sa.Column("consent_status", sa.String(), server_default="active", nullable=False))
    op.add_column("family_bindings", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("family_bindings", sa.Column("revoked_at", sa.DateTime(), nullable=True))
    op.add_column("family_bindings", sa.Column("revoke_reason", sa.Text(), nullable=True))
    op.add_column("family_bindings", sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False))
    op.create_foreign_key("fk_family_bindings_household", "family_bindings", "households", ["household_id"], ["id"])
    op.execute(
        """
        UPDATE family_bindings
        SET status = 'pending_consent', consent_status = 'pending_reconsent'
        """
    )

    op.create_table(
        "binding_audit_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("binding_id", sa.UUID(), nullable=True),
        sa.Column("household_id", sa.UUID(), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["binding_id"], ["family_bindings.id"]),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_binding_audit_events_binding", "binding_audit_events", ["binding_id", "created_at"], unique=False)

    op.execute(
        """
        INSERT INTO households (elder_user_id, name)
        SELECT DISTINCT fb.elder_user_id, 'Household'
        FROM family_bindings fb
        WHERE NOT EXISTS (
            SELECT 1 FROM households h WHERE h.elder_user_id = fb.elder_user_id
        )
        """
    )
    op.execute(
        """
        UPDATE family_bindings fb
        SET household_id = h.id
        FROM households h
        WHERE fb.elder_user_id = h.elder_user_id AND fb.household_id IS NULL
        """
    )
    op.execute(
        """
        INSERT INTO care_circle_members (household_id, user_id, role, status, permissions)
        SELECT h.id, h.elder_user_id, 'elder', 'active', ARRAY['owner']::text[]
        FROM households h
        ON CONFLICT (household_id, user_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO care_circle_members (household_id, user_id, role, status, permissions)
        SELECT fb.household_id, fb.family_user_id, 'family', fb.status, fb.permissions
        FROM family_bindings fb
        WHERE fb.household_id IS NOT NULL
        ON CONFLICT (household_id, user_id) DO NOTHING
        """
    )
    op.alter_column("family_bindings", "household_id", nullable=False)

    op.create_table(
        "contact_points",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="1", nullable=False),
        sa.Column("availability_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("verification_state", sa.String(), server_default="unverified", nullable=False),
        sa.Column("verification_challenge_hash", sa.String(), nullable=True),
        sa.Column("verification_attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("verification_locked_at", sa.DateTime(), nullable=True),
        sa.Column("verification_outbox_id", sa.UUID(), nullable=True),
        sa.Column("challenge_expires_at", sa.DateTime(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["verification_outbox_id"], ["notification_outbox.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "kind", "value", name="uq_contact_points_household_kind_value"),
    )
    op.create_index("idx_contact_points_household", "contact_points", ["household_id", "status", "priority"], unique=False)

    op.add_column("emergency_contacts", sa.Column("household_id", sa.UUID(), nullable=True))
    op.add_column("emergency_contacts", sa.Column("contact_point_id", sa.UUID(), nullable=True))
    op.add_column("emergency_contacts", sa.Column("availability_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("emergency_contacts", sa.Column("verification_state", sa.String(), server_default="legacy_unverified", nullable=False))
    op.add_column("emergency_contacts", sa.Column("verified_at", sa.DateTime(), nullable=True))
    op.add_column("emergency_contacts", sa.Column("revoked_at", sa.DateTime(), nullable=True))
    op.add_column("emergency_contacts", sa.Column("revoke_reason", sa.Text(), nullable=True))
    op.add_column("emergency_contacts", sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False))
    op.create_foreign_key("fk_emergency_contacts_household", "emergency_contacts", "households", ["household_id"], ["id"])
    op.create_foreign_key("fk_emergency_contacts_contact_point", "emergency_contacts", "contact_points", ["contact_point_id"], ["id"])

    op.create_table(
        "escalation_policies",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("household_id", "version", name="uq_escalation_policies_household_version"),
    )
    op.create_index("idx_escalation_policies_household", "escalation_policies", ["household_id", "status"], unique=False)
    op.create_table(
        "escalation_steps",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("policy_id", sa.UUID(), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("contact_point_id", sa.UUID(), nullable=True),
        sa.Column("delay_seconds", sa.Integer(), server_default="0", nullable=False),
        sa.Column("config_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["escalation_policies.id"]),
        sa.ForeignKeyConstraint(["contact_point_id"], ["contact_points.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_id", "step_order", name="uq_escalation_steps_policy_order"),
    )
    op.create_index("idx_escalation_steps_policy", "escalation_steps", ["policy_id", "step_order"], unique=False)

    op.add_column("notification_outbox", sa.Column("reconciliation_state", sa.String(), server_default="not_required", nullable=False))
    op.add_column("notification_outbox", sa.Column("reconciled_at", sa.DateTime(), nullable=True))
    op.add_column("notification_receipts", sa.Column("signature_timestamp", sa.DateTime(), nullable=True))
    op.create_table(
        "notification_reconciliations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("outbox_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("state", sa.String(), server_default="pending", nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("observed_state", sa.String(), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["outbox_id"], ["notification_outbox.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outbox_id", "reason", name="uq_notification_reconciliation_reason"),
    )
    op.create_index("idx_notification_reconciliations_state", "notification_reconciliations", ["state", "created_at"], unique=False)

    op.add_column("operator_cases", sa.Column("assigned_at", sa.DateTime(), nullable=True))
    op.add_column("operator_cases", sa.Column("sla_deadline_at", sa.DateTime(), nullable=True))
    op.add_column("operator_cases", sa.Column("state_version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("operator_cases", sa.Column("reopened_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE operator_cases SET status = 'unstaffed' WHERE owner_id IS NULL")
    op.create_check_constraint(
        "ck_operator_cases_owner_status",
        "operator_cases",
        "(status = 'unstaffed' AND owner_id IS NULL) OR (status <> 'unstaffed' AND owner_id IS NOT NULL)",
    )
    op.create_table(
        "case_activities",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("activity_type", sa.String(), nullable=False),
        sa.Column("from_status", sa.String(), nullable=True),
        sa.Column("to_status", sa.String(), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["operator_cases.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_case_activities_case", "case_activities", ["case_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_case_activities_case", table_name="case_activities")
    op.drop_table("case_activities")
    op.drop_constraint("ck_operator_cases_owner_status", "operator_cases", type_="check")
    op.drop_column("operator_cases", "reopened_at")
    op.drop_column("operator_cases", "state_version")
    op.drop_column("operator_cases", "sla_deadline_at")
    op.drop_column("operator_cases", "assigned_at")
    op.drop_index("idx_notification_reconciliations_state", table_name="notification_reconciliations")
    op.drop_table("notification_reconciliations")
    op.drop_column("notification_receipts", "signature_timestamp")
    op.drop_column("notification_outbox", "reconciled_at")
    op.drop_column("notification_outbox", "reconciliation_state")
    op.drop_index("idx_escalation_steps_policy", table_name="escalation_steps")
    op.drop_table("escalation_steps")
    op.drop_index("idx_escalation_policies_household", table_name="escalation_policies")
    op.drop_table("escalation_policies")
    op.drop_constraint("fk_emergency_contacts_contact_point", "emergency_contacts", type_="foreignkey")
    op.drop_constraint("fk_emergency_contacts_household", "emergency_contacts", type_="foreignkey")
    op.drop_column("emergency_contacts", "updated_at")
    op.drop_column("emergency_contacts", "revoke_reason")
    op.drop_column("emergency_contacts", "revoked_at")
    op.drop_column("emergency_contacts", "verified_at")
    op.drop_column("emergency_contacts", "verification_state")
    op.drop_column("emergency_contacts", "availability_json")
    op.drop_column("emergency_contacts", "contact_point_id")
    op.drop_column("emergency_contacts", "household_id")
    op.drop_index("idx_contact_points_household", table_name="contact_points")
    op.drop_table("contact_points")
    op.drop_index("idx_binding_audit_events_binding", table_name="binding_audit_events")
    op.drop_table("binding_audit_events")
    op.alter_column("family_bindings", "household_id", nullable=True)
    op.drop_constraint("fk_family_bindings_household", "family_bindings", type_="foreignkey")
    op.drop_column("family_bindings", "updated_at")
    op.drop_column("family_bindings", "revoke_reason")
    op.drop_column("family_bindings", "revoked_at")
    op.drop_column("family_bindings", "version")
    op.drop_column("family_bindings", "consent_status")
    op.drop_column("family_bindings", "status")
    op.drop_column("family_bindings", "household_id")
    op.drop_index("idx_household_invites_household_status", table_name="household_invites")
    op.drop_table("household_invites")
    op.drop_index("idx_care_circle_members_user", table_name="care_circle_members")
    op.drop_table("care_circle_members")
    op.drop_index("idx_households_elder", table_name="households")
    op.drop_table("households")
