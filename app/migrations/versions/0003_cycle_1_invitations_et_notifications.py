"""cycle 1 invitations et notifications

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event_actions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_event_actions_actor_id__users")
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name=op.f("fk_event_actions_event_id__events")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_actions")),
    )
    with op.batch_alter_table("event_actions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_event_actions_event_id"), ["event_id"], unique=False
        )

    op.create_table(
        "event_operations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_event_operations_actor_id__users")
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_event_operations_event_id__events"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_operations")),
    )
    with op.batch_alter_table("event_operations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_event_operations_event_id"), ["event_id"], unique=False
        )

    with op.batch_alter_table("auth_sessions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "pending_event_invitation_id", sa.String(length=64), nullable=True
            )
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_auth_sessions_pending_event_invitation_id__invitations"),
            "invitations",
            ["pending_event_invitation_id"],
            ["id"],
        )

    with op.batch_alter_table("changes", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("sequence", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("operation_id", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "notification_scope",
                sa.String(length=16),
                server_default="none",
                nullable=False,
            )
        )
        batch_op.create_index(
            batch_op.f("ix_changes_operation_id"), ["operation_id"], unique=False
        )

    with op.batch_alter_table("invitation_responses", schema=None) as batch_op:
        batch_op.alter_column(
            "actor_id", existing_type=sa.VARCHAR(length=64), nullable=True
        )

    with op.batch_alter_table("invitations", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "purpose",
                sa.String(length=20),
                server_default="invitation",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("invitee_name", sa.String(length=120), nullable=True)
        )

    with op.batch_alter_table("mail_deliveries", schema=None) as batch_op:
        batch_op.add_column(sa.Column("event_id", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("event_invitation_id", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("notification_id", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(sa.Column("user_id", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column(
                "kind",
                sa.String(length=32),
                server_default="organizer_invitation",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("recipient", sa.String(length=254), nullable=True)
        )
        batch_op.add_column(sa.Column("subject", sa.String(length=240), nullable=True))
        batch_op.alter_column(
            "invitation_id", existing_type=sa.VARCHAR(length=64), nullable=True
        )
        batch_op.create_index(
            batch_op.f("ix_mail_deliveries_event_id"), ["event_id"], unique=False
        )
        batch_op.create_unique_constraint(
            batch_op.f("uq_mail_deliveries_notification_id_"), ["notification_id"]
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_mail_deliveries_notification_id__notifications"),
            "notifications",
            ["notification_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_mail_deliveries_user_id__users"),
            "users",
            ["user_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_mail_deliveries_event_id__events"),
            "events",
            ["event_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_mail_deliveries_event_invitation_id__invitations"),
            "invitations",
            ["event_invitation_id"],
            ["id"],
        )

    with op.batch_alter_table("notification_changes", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("active", sa.Boolean(), server_default="1", nullable=False)
        )

    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("opened_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("due_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column("reason", sa.Text(), server_default="", nullable=False)
        )
        batch_op.add_column(
            sa.Column(
                "naive_requests", sa.Integer(), server_default="0", nullable=False
            )
        )
        batch_op.create_index(
            batch_op.f("ix_notifications_due_at"), ["due_at"], unique=False
        )


def downgrade():
    # Les réponses anonymes et les nouvelles tentatives ne sont pas représentables en 0002.
    connection = op.get_bind()
    if (
        connection.scalar(sa.text("SELECT count(*) FROM event_operations"))
        or connection.scalar(sa.text("SELECT count(*) FROM event_actions"))
        or connection.scalar(
            sa.text("SELECT count(*) FROM mail_deliveries WHERE invitation_id IS NULL")
        )
        or connection.scalar(
            sa.text("SELECT count(*) FROM invitation_responses WHERE actor_id IS NULL")
        )
    ):
        raise RuntimeError(
            "Rétrogradation refusée : des données du cycle 1 seraient perdues. Restaurer une sauvegarde compatible."
        )
    op.drop_index("ix_notifications_due_at", table_name="notifications")
    for name in ("naive_requests", "reason", "due_at", "opened_at"):
        op.drop_column("notifications", name)
    op.drop_column("notification_changes", "active")
    with op.batch_alter_table("mail_deliveries") as batch_op:
        for name in (
            "fk_mail_deliveries_event_invitation_id__invitations",
            "fk_mail_deliveries_event_id__events",
            "fk_mail_deliveries_user_id__users",
            "fk_mail_deliveries_notification_id__notifications",
        ):
            batch_op.drop_constraint(name, type_="foreignkey")
        batch_op.drop_constraint("uq_mail_deliveries_notification_id_", type_="unique")
        batch_op.drop_index("ix_mail_deliveries_event_id")
        batch_op.alter_column(
            "invitation_id", existing_type=sa.String(64), nullable=False
        )
        for name in (
            "subject",
            "recipient",
            "kind",
            "user_id",
            "notification_id",
            "event_invitation_id",
            "event_id",
        ):
            batch_op.drop_column(name)
    op.drop_column("invitations", "invitee_name")
    op.drop_column("invitations", "purpose")
    with op.batch_alter_table("invitation_responses") as batch_op:
        batch_op.alter_column("actor_id", existing_type=sa.String(64), nullable=False)
    op.drop_index("ix_changes_operation_id", table_name="changes")
    for name in ("notification_scope", "operation_id", "sequence"):
        op.drop_column("changes", name)
    with op.batch_alter_table("auth_sessions") as batch_op:
        batch_op.drop_constraint(
            "fk_auth_sessions_pending_event_invitation_id__invitations",
            type_="foreignkey",
        )
        batch_op.drop_column("pending_event_invitation_id")
    op.drop_table("event_operations")
    op.drop_table("event_actions")
