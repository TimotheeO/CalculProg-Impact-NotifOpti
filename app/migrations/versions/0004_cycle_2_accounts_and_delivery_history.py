"""Comptes, reprise durable et historique des tentatives du cycle 2."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "password_resets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_digest", sa.String(64), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_password_resets_user_id", "password_resets", ["user_id"])
    with op.batch_alter_table("auth_sessions") as batch:
        batch.add_column(sa.Column("pending_password_reset_id", sa.String(64)))
        batch.create_foreign_key(
            "fk_auth_sessions_password_reset",
            "password_resets",
            ["pending_password_reset_id"],
            ["id"],
        )
    with op.batch_alter_table("mail_deliveries") as batch:
        batch.add_column(sa.Column("password_reset_id", sa.String(64)))
        batch.create_foreign_key(
            "fk_mail_deliveries_password_reset",
            "password_resets",
            ["password_reset_id"],
            ["id"],
        )
        batch.add_column(
            sa.Column("context", sa.JSON(), server_default="{}", nullable=False)
        )
        batch.add_column(
            sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False)
        )
    op.add_column(
        "notifications",
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "notifications",
        sa.Column("replaced_fields", sa.JSON(), server_default="[]", nullable=False),
    )
    op.create_table(
        "mail_attempts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "delivery_id",
            sa.String(64),
            sa.ForeignKey("mail_deliveries.id"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(64), sa.ForeignKey("users.id")),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider_id", sa.String(240)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("content_revision", sa.Integer()),
        sa.UniqueConstraint("delivery_id", "number"),
    )
    op.create_index("ix_mail_attempts_delivery_id", "mail_attempts", ["delivery_id"])
    op.execute(
        sa.text("""INSERT INTO mail_attempts
        (id, delivery_id, number, started_at, finished_at, status, provider_id, error_code)
        SELECT id, id, 1, attempted_at,
        CASE WHEN status = 'sending' THEN NULL ELSE attempted_at END,
        status, provider_id, error_code FROM mail_deliveries WHERE attempted_at IS NOT NULL""")
    )
    op.execute(
        sa.text(
            "UPDATE mail_deliveries SET attempt_count = 1 WHERE attempted_at IS NOT NULL"
        )
    )


def downgrade():
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT count(*) FROM password_resets")
    ) or connection.scalar(
        sa.text("SELECT count(*) FROM mail_attempts WHERE id != delivery_id")
    ):
        raise RuntimeError(
            "La base contient des données du cycle 2. Restaurez une sauvegarde compatible au lieu de les supprimer."
        )
    op.drop_table("mail_attempts")
    op.drop_column("notifications", "replaced_fields")
    op.drop_column("notifications", "revision")
    with op.batch_alter_table("mail_deliveries") as batch:
        batch.drop_constraint("fk_mail_deliveries_password_reset", type_="foreignkey")
        for column in ("password_reset_id", "context", "attempt_count"):
            batch.drop_column(column)
    with op.batch_alter_table("auth_sessions") as batch:
        batch.drop_constraint("fk_auth_sessions_password_reset", type_="foreignkey")
        batch.drop_column("pending_password_reset_id")
    op.drop_table("password_resets")
