from datetime import datetime, timedelta, timezone

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, StatementError

from app.database import Database
from app.models import (
    Base,
    Change,
    Dependency,
    Enrollment,
    Invitation,
    InvitationWorkshop,
    Notification,
    NotificationChange,
    User,
    Workshop,
)
from app.seeds import EVENT_ID, OWNER_ID, SECOND_EVENT_ID, seed_demo
from app.services import DomainError


def test_migration_is_repeatable_and_preserves_existing_data(seeded_db):
    seeded_db.initialize()
    seeded_db.check_schema()
    with seeded_db.sessions() as session:
        assert session.get(User, "demo-alice").name == "Alice Martin"
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
    with seeded_db.engine.connect() as connection:
        assert (
            compare_metadata(MigrationContext.configure(connection), Base.metadata)
            == []
        )


def test_foreign_keys_are_enabled_on_every_connection(database):
    with database.engine.connect() as first, database.engine.connect() as second:
        assert first.scalar(text("PRAGMA foreign_keys")) == 1
        assert second.scalar(text("PRAGMA foreign_keys")) == 1


@pytest.mark.parametrize(
    "record",
    [
        lambda: Dependency(
            event_id=EVENT_ID,
            base_workshop_id="w1",
            dependent_workshop_id="fabrique-photo",
        ),
        lambda: Enrollment(
            event_id=EVENT_ID, user_id="demo-alice", workshop_id="fabrique-photo"
        ),
        lambda: InvitationWorkshop(
            event_id=EVENT_ID,
            invitation_id="invitation-alice",
            workshop_id="fabrique-photo",
        ),
        lambda: Change(
            id="bad-change",
            event_id=EVENT_ID,
            workshop_id="fabrique-photo",
            actor_id=OWNER_ID,
            field="location",
            old_value="A",
            new_value="B",
        ),
        lambda: NotificationChange(
            event_id=EVENT_ID,
            notification_id="seed-notification",
            change_id="seed-cancellation",
        ),
    ],
)
def test_database_rejects_cross_event_links(seeded_db, record):
    with pytest.raises(IntegrityError), seeded_db.transaction() as session:
        session.add(record())
        session.flush()
    with seeded_db.engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []


def test_enrollment_requires_a_participation_in_the_same_event(seeded_db):
    with pytest.raises(IntegrityError), seeded_db.transaction() as session:
        session.add(
            Enrollment(event_id=EVENT_ID, user_id="demo-chloe", workshop_id="w1")
        )
        session.flush()


def test_duplicate_enrollment_is_rejected(seeded_db):
    with pytest.raises(IntegrityError), seeded_db.transaction() as session:
        session.add(
            Enrollment(event_id=EVENT_ID, user_id="demo-alice", workshop_id="w1")
        )
        session.flush()


def test_self_dependency_is_rejected(seeded_db):
    with pytest.raises(IntegrityError), seeded_db.transaction() as session:
        session.add(
            Dependency(
                event_id=EVENT_ID, base_workshop_id="w1", dependent_workshop_id="w1"
            )
        )
        session.flush()


@pytest.mark.parametrize(
    "field, value",
    [
        ("capacity", 0),
        ("capacity", -1),
        ("status", "invented"),
        ("name", "  "),
        ("ends_at", datetime(2026, 10, 22, 11, tzinfo=timezone.utc)),
    ],
)
def test_database_rejects_invalid_workshop_state(seeded_db, field, value):
    with pytest.raises(IntegrityError), seeded_db.transaction() as session:
        setattr(session.get(Workshop, "w1"), field, value)
        session.flush()


def test_email_normalization_and_uniqueness(database):
    with database.transaction() as session:
        session.add(User(id="one", email="  ALICE@EXAMPLE.TEST ", name="Alice"))
    with database.sessions() as session:
        assert session.get(User, "one").email == "alice@example.test"
    with pytest.raises(IntegrityError), database.transaction() as session:
        session.add(User(id="two", email="Alice@example.test", name="Autre Alice"))
        session.flush()


def test_naive_datetime_is_rejected(seeded_db):
    with (
        pytest.raises(StatementError, match="fuseau"),
        seeded_db.transaction() as session,
    ):
        session.get(Workshop, "w1").starts_at = datetime(
            2026, 10, 22, 14, tzinfo=timezone.utc
        ).replace(tzinfo=None)
        session.flush()


def test_timezone_is_normalized_to_utc_and_restored_after_reopen(seeded_db):
    with seeded_db.transaction() as session:
        session.get(Workshop, "w1").starts_at = datetime(
            2026, 10, 22, 14, tzinfo=timezone(timedelta(hours=2))
        )
    reopened = Database(seeded_db.url)
    try:
        with reopened.sessions() as session:
            assert session.get(Workshop, "w1").starts_at == datetime(
                2026, 10, 22, 12, tzinfo=timezone.utc
            )
            assert session.get(Workshop, "w1").starts_at.tzinfo is timezone.utc
    finally:
        reopened.close()


def test_transaction_rolls_back_every_write_after_failure(seeded_db):
    with (
        pytest.raises(RuntimeError, match="abandon"),
        seeded_db.transaction() as session,
    ):
        session.get(Workshop, "w1").location = "Ne doit pas rester"
        session.add(
            User(id="transient", name="Transitoire", email="transient@example.test")
        )
        session.flush()
        raise RuntimeError("abandon")
    with seeded_db.sessions() as session:
        assert session.get(User, "transient") is None
        assert session.get(Workshop, "w1").location == "La Cuisine"


def test_seed_is_idempotent_and_does_not_overwrite_changes(seeded_db):
    with seeded_db.transaction() as session:
        session.get(Workshop, "w1").location = "Nouvelle salle"
    with seeded_db.transaction() as session:
        assert seed_demo(session) is False
    with seeded_db.sessions() as session:
        assert session.get(Workshop, "w1").location == "Nouvelle salle"
        assert session.scalar(select(func.count()).select_from(Invitation)) == 10
        assert session.scalar(select(func.count()).select_from(Notification)) == 1
        assert session.scalar(select(func.count()).select_from(NotificationChange)) == 2
        assert session.get(Workshop, "fabrique-photo").event_id == SECOND_EVENT_ID


def test_seed_refuses_a_nonempty_database_without_demo(database):
    with database.transaction() as session:
        session.add(User(id="real", name="Existant", email="existing@example.test"))
    with (
        pytest.raises(DomainError, match="base vide"),
        database.transaction() as session,
    ):
        seed_demo(session)
    with database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1


def test_uninitialized_database_is_detected(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'empty.sqlite3'}")
    try:
        with pytest.raises(RuntimeError, match="init-db"):
            database.check_schema()
    finally:
        database.close()
