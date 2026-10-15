from datetime import timezone

import pytest
from sqlalchemy import func, select

from app.database import Database
from app.models import Change, Event, User, Workshop
from app.seeds import EVENT_ID, OWNER_ID
from app.services import Forbidden, InvalidChange, NotFound, change_workshop_location


def test_current_state_and_audit_history_survive_a_new_engine(seeded_db):
    with seeded_db.transaction() as session:
        change = change_workshop_location(
            session, EVENT_ID, "w1", OWNER_ID, " Salle Bordeaux "
        )
        change_id = change.id
    reopened = Database(seeded_db.url)
    try:
        with reopened.sessions() as session:
            assert session.get(Workshop, "w1").location == "Salle Bordeaux"
            persisted = session.get(Change, change_id)
            assert persisted.old_value == "La Cuisine"
            assert persisted.new_value == "Salle Bordeaux"
            assert persisted.actor_id == OWNER_ID
            assert persisted.event_id == EVENT_ID
            assert persisted.workshop_id == "w1"
            assert persisted.created_at.tzinfo is timezone.utc
    finally:
        reopened.close()


def test_identical_value_creates_no_change(seeded_db):
    with seeded_db.transaction() as session:
        before = session.scalar(select(func.count()).select_from(Change))
        assert (
            change_workshop_location(session, EVENT_ID, "w1", OWNER_ID, " La Cuisine ")
            is None
        )
        assert session.scalar(select(func.count()).select_from(Change)) == before


@pytest.mark.parametrize("actor", ["demo-alice", "missing"])
def test_unauthorized_actor_cannot_modify_or_create_history(seeded_db, actor):
    with seeded_db.sessions() as session:
        before = session.scalar(select(func.count()).select_from(Change))
    with pytest.raises(Forbidden), seeded_db.transaction() as session:
        change_workshop_location(session, EVENT_ID, "w1", actor, "Refusé")
    with seeded_db.sessions() as session:
        assert session.get(Workshop, "w1").location == "La Cuisine"
        assert session.scalar(select(func.count()).select_from(Change)) == before


def test_other_event_owner_without_permission_is_rejected(seeded_db):
    # Thomas n’est pas organisateur de l’événement de Léa.
    with pytest.raises(Forbidden), seeded_db.transaction() as session:
        change_workshop_location(
            session, "demo-fabrique", "fabrique-photo", OWNER_ID, "Refusé"
        )


def test_authorized_coorganizer_can_modify_event(seeded_db):
    with seeded_db.transaction() as session:
        assert (
            change_workshop_location(
                session, EVENT_ID, "w1", "demo-lea", "Salle C"
            ).actor_id
            == "demo-lea"
        )


def test_disabled_organizer_is_rejected(seeded_db):
    with seeded_db.transaction() as session:
        session.get(User, OWNER_ID).is_active = False
    with pytest.raises(Forbidden), seeded_db.transaction() as session:
        change_workshop_location(session, EVENT_ID, "w1", OWNER_ID, "Refusé")


@pytest.mark.parametrize("status", ["archived", "cancelled"])
def test_closed_event_cannot_be_modified(seeded_db, status):
    with seeded_db.transaction() as session:
        session.get(Event, EVENT_ID).status = status
    with pytest.raises(InvalidChange), seeded_db.transaction() as session:
        change_workshop_location(session, EVENT_ID, "w1", OWNER_ID, "Refusé")


@pytest.mark.parametrize(
    "event_id, workshop_id",
    [
        ("missing", "w1"),
        (EVENT_ID, "missing"),
        (EVENT_ID, "fabrique-photo"),
    ],
)
def test_missing_or_cross_event_target_is_rejected(seeded_db, event_id, workshop_id):
    with pytest.raises(NotFound), seeded_db.transaction() as session:
        change_workshop_location(session, event_id, workshop_id, OWNER_ID, "Refusé")


@pytest.mark.parametrize("location", ["", "   ", "A" * 241])
def test_invalid_location_is_rejected_without_mutation(seeded_db, location):
    with pytest.raises(InvalidChange), seeded_db.transaction() as session:
        change_workshop_location(session, EVENT_ID, "w1", OWNER_ID, location)
    with seeded_db.sessions() as session:
        assert session.get(Workshop, "w1").location == "La Cuisine"


def test_failure_after_audited_change_rolls_back_state_and_history(seeded_db):
    with pytest.raises(RuntimeError), seeded_db.transaction() as session:
        change = change_workshop_location(
            session, EVENT_ID, "w1", OWNER_ID, "À annuler"
        )
        change_id = change.id
        raise RuntimeError("échec après écriture")
    with seeded_db.sessions() as session:
        assert session.get(Workshop, "w1").location == "La Cuisine"
        assert session.get(Change, change_id) is None
