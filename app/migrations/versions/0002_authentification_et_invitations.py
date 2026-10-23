"""authentification et invitations organisateurs

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_rate_limits",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.CheckConstraint("attempts > 0", name=op.f("ck_auth_rate_limits_attempts")),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_auth_rate_limits")),
    )
    op.create_table(
        "auth_audit",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("target_user_id", sa.String(length=64), nullable=True),
        sa.Column("invitation_id", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_auth_audit_actor_id__users")
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id"],
            ["organizer_invitations.id"],
            name=op.f("fk_auth_audit_invitation_id__organizer_invitations"),
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name=op.f("fk_auth_audit_target_user_id__users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_audit")),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("pending_invitation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_auth_sessions_expiry")
        ),
        sa.ForeignKeyConstraint(
            ["pending_invitation_id"],
            ["organizer_invitations.id"],
            name=op.f("fk_auth_sessions_pending_invitation_id__organizer_invitations"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_auth_sessions_user_id__users")
        ),
        sa.PrimaryKeyConstraint("token_digest", name=op.f("pk_auth_sessions")),
    )
    with op.batch_alter_table("auth_sessions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_auth_sessions_user_id"), ["user_id"], unique=False
        )

    op.create_table(
        "mail_deliveries",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("invitation_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("backend", sa.String(length=20), nullable=False),
        sa.Column("attempted_at", sa.DateTime(), nullable=True),
        sa.Column("provider_id", sa.String(length=240), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'simulated', 'accepted', 'failed', 'uncertain')",
            name=op.f("ck_mail_deliveries_status"),
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id"],
            ["organizer_invitations.id"],
            name=op.f("fk_mail_deliveries_invitation_id__organizer_invitations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_deliveries")),
        sa.UniqueConstraint(
            "invitation_id", name=op.f("uq_mail_deliveries_invitation_id_")
        ),
    )
    with op.batch_alter_table("organizer_invitations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("accepted_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column("accepted_user_id", sa.String(length=64), nullable=True)
        )
        batch_op.create_index(
            "uq_organizer_pending_email",
            ["email"],
            unique=True,
            sqlite_where=sa.text("status = 'pending'"),
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_organizer_invitations_accepted_user_id__users"),
            "users",
            ["accepted_user_id"],
            ["id"],
        )


def downgrade():
    op.drop_table("mail_deliveries")
    op.drop_table("auth_sessions")
    op.drop_table("auth_audit")
    op.drop_table("auth_rate_limits")
    with op.batch_alter_table("organizer_invitations", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_organizer_invitations_accepted_user_id__users"),
            type_="foreignkey",
        )
        batch_op.drop_index(
            "uq_organizer_pending_email", sqlite_where=sa.text("status = 'pending'")
        )
        batch_op.drop_column("accepted_user_id")
        batch_op.drop_column("accepted_at")
