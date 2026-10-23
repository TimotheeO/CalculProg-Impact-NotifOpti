"""Mise à niveau de bases peuplées et refus d’une rétrogradation destructrice."""

from datetime import timedelta

import pytest
from alembic import command
from sqlalchemy import MetaData, select, text

from app.auth.security import digest
from app.database import Database, migration_config
from app.models import (
    AuthSession,
    Base,
    EventAction,
    Invitation,
    MailDelivery,
    OrganizerInvitation,
)
from app.seeds import EVENT_ID, OWNER_ID
from tests.web.test_events import NOW


def migrate(database, direction, version):
    config = migration_config()
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        getattr(command, direction)(config, version)


def test_0002_populated_sessions_invitations_and_attempts_upgrade_without_loss(
    seeded_db, tmp_path
):
    database = Database(f"sqlite:///{tmp_path / 'legacy-0002.sqlite3'}")
    try:
        migrate(database, "upgrade", "0002")
        legacy = MetaData()
        legacy.reflect(database.engine)
        with database.engine.begin() as target, seeded_db.engine.connect() as source:
            for table in legacy.sorted_tables:
                if table.name == "alembic_version":
                    continue
                columns = [
                    Base.metadata.tables[table.name].c[c.name] for c in table.columns
                ]
                rows = source.execute(select(*columns)).mappings().all()
                if rows:
                    target.execute(table.insert(), [dict(row) for row in rows])
            target.execute(
                legacy.tables["organizer_invitations"].insert(),
                {
                    "id": "old-invite",
                    "email": "old@example.test",
                    "inviter_id": OWNER_ID,
                    "token_digest": digest("old-token"),
                    "status": "pending",
                    "created_at": NOW,
                    "expires_at": NOW + timedelta(hours=48),
                },
            )
            target.execute(
                legacy.tables["auth_sessions"].insert(),
                {
                    "token_digest": digest("session"),
                    "csrf_token": "csrf",
                    "user_id": OWNER_ID,
                    "pending_invitation_id": "old-invite",
                    "created_at": NOW,
                    "expires_at": NOW + timedelta(hours=8),
                },
            )
            target.execute(
                legacy.tables["mail_deliveries"].insert(),
                {
                    "id": "old-mail",
                    "invitation_id": "old-invite",
                    "backend": "memory",
                    "status": "simulated",
                    "created_at": NOW,
                    "attempted_at": NOW,
                },
            )
        database.initialize()
        database.check_schema()
        with database.sessions() as session:
            assert (
                session.get(AuthSession, digest("session")).pending_invitation_id
                == "old-invite"
            )
            assert (
                session.get(AuthSession, digest("session")).pending_event_invitation_id
                is None
            )
            assert session.get(MailDelivery, "old-mail").status == "simulated"
            assert session.get(MailDelivery, "old-mail").kind == "organizer_invitation"
            assert session.get(Invitation, "invitation-alice").purpose == "invitation"
            assert (
                session.get(OrganizerInvitation, "old-invite").email
                == "old@example.test"
            )
            assert session.execute(text("PRAGMA foreign_key_check")).all() == []
        migrate(database, "downgrade", "0002")
        database.initialize()
        database.check_schema()
    finally:
        database.close()


def test_downgrade_refuses_new_business_data_and_rolls_back(seeded_db):
    with seeded_db.transaction() as session:
        session.add(
            EventAction(
                id="new-action",
                event_id=EVENT_ID,
                actor_id=OWNER_ID,
                kind="test",
                detail={},
                created_at=NOW,
            )
        )
    with pytest.raises(RuntimeError, match="perdues"):
        migrate(seeded_db, "downgrade", "0002")
    seeded_db.check_schema()
    with seeded_db.sessions() as session:
        assert session.get(EventAction, "new-action") is not None
