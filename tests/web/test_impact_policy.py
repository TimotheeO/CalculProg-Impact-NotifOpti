"""Les destinataires dépendent de la conséquence métier, champ par champ."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.events.services import parse_local, workshops_for
from app.impact import workshop_change_audience, workshop_plan_audience
from app.journal import snapshot
from app.models import (
    Change,
    Dependency,
    Notification,
    NotificationChange,
    User,
    Workshop,
)
from app.notification_groups import attach_change
from app.seeds import EVENT_ID, OWNER_ID
from app.web import create_app
from app.workshops.planning import plan_change
from app.workshops.types import snapshot as workshop_snapshot
from tests.web.test_cycle1 import (
    change,
    groups,
    worker,
)
from tests.web.test_events import HASHED, NOW, hidden, login

DIRECT = {"demo-alice", "demo-sofia"}
CASCADE = DIRECT | {"demo-mehdi", "demo-lina"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("location", "Salle B"),
        ("name", "Cuisine conviviale"),
        ("description", "Nouvelle description"),
        ("capacity", 15),
    ],
)
def test_local_fields_only_direct_enrollments(seeded_db, field, value):
    with seeded_db.sessions() as session:
        impact = workshop_change_audience(session, EVENT_ID, "w1", {field: value})
        assert {u.id for u in impact.users} == DIRECT
        assert {w.id for w in impact.workshops} == {"w1"}
        assert len(impact.spared) == 6 and not impact.propagated
        assert all("directe" in reason for reason in impact.reasons.values())


@pytest.mark.parametrize(
    "field,value",
    [
        ("ends_at", "2026-10-22T15:10"),
        ("status", "cancelled"),
    ],
)
def test_schedule_and_cancellation_traverse_dependencies(seeded_db, field, value):
    with seeded_db.sessions() as session:
        proposed = replace(
            workshop_snapshot(session.get(Workshop, "w1")),
            **{field: parse_local(value) if field == "ends_at" else value},
        )
        plan = plan_change(
            workshops_for(session, EVENT_ID),
            list(
                session.scalars(
                    select(Dependency).where(Dependency.event_id == EVENT_ID)
                )
            ),
            "w1",
            proposed,
        )
        impact = workshop_plan_audience(session, EVENT_ID, plan)
        assert {u.id for u in impact.users} == CASCADE
        assert {w.id for w in impact.workshops} == {"w1", "w2", "w3"}
        assert len(impact.spared) == 4 and impact.propagated
        assert "après « Cuisine" in impact.reasons["demo-mehdi"]


def test_mixed_change_sends_room_only_to_direct_people(
    seeded_db, web_settings, web_clock
):
    change(seeded_db, web_clock, location="Salle B", ends_at="2026-10-22T15:10")
    assert {n.user_id for n in groups(seeded_db)} == CASCADE
    web_clock.advance(60)
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    scheduler.tick()
    assert len(scheduler.mailer.messages) == 4
    for message in scheduler.mailer.messages:
        assert (
            "16 h 10" if message.recipient == "demo-lina@example.test" else "15 h 10"
        ) in message.text
        if message.recipient in {"demo-alice@example.test", "demo-sofia@example.test"}:
            assert "Salle B" in message.text
        else:
            assert "Salle B" not in message.text and "lieu :" not in message.text
    with seeded_db.sessions() as session:
        assert snapshot(session, event_id=EVENT_ID)[2] == {
            "naive": 4,
            "final": 4,
            "saved": 0,
            "closed": 4,
        }


def test_separate_local_then_cascade_windows_keep_distinct_content_and_deadlines(
    seeded_db, web_settings, web_clock
):
    change(seeded_db, web_clock, location="Salle B")
    web_clock.advance(20)
    change(seeded_db, web_clock, ends_at="2026-10-22T15:10")
    notifications = {n.user_id: n for n in groups(seeded_db)}
    assert {notifications[user].due_at for user in DIRECT} == {
        NOW + timedelta(seconds=60)
    }
    assert {notifications[user].due_at for user in CASCADE - DIRECT} == {
        NOW + timedelta(seconds=80)
    }
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    web_clock.advance(40)
    scheduler.tick()
    assert len(scheduler.mailer.messages) == 2
    web_clock.advance(20)
    scheduler.tick()
    assert len(scheduler.mailer.messages) == 4
    for message in scheduler.mailer.messages:
        if message.recipient in {"demo-mehdi@example.test", "demo-lina@example.test"}:
            assert "Salle B" not in message.text
    with seeded_db.sessions() as session:
        assert snapshot(session, event_id=EVENT_ID)[2] == {
            "naive": 6,
            "final": 4,
            "saved": 2,
            "closed": 4,
        }


def test_dependency_edit_does_not_expand_local_change(
    seeded_db, web_settings, web_clock
):
    from app.workshops.services import change_dependency

    change(seeded_db, web_clock, location="Salle B")
    web_clock.advance(20)
    with seeded_db.transaction(immediate=True) as session:
        change_dependency(
            session, EVENT_ID, OWNER_ID, "w1", "w4", False, web_clock(), 60
        )
    assert {n.user_id for n in groups(seeded_db)} == DIRECT
    web_clock.advance(40)
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    scheduler.tick()
    assert len(scheduler.mailer.messages) == 2


def test_old_broad_pending_room_targets_recalculated_before_dispatch(
    seeded_db, web_settings, web_clock
):
    # Représente un groupe non envoyé créé par l’ancienne règle tout-en-cascade.
    with seeded_db.transaction(immediate=True) as session:
        session.get(Workshop, "w1").location = "Salle B"
        legacy = Change(
            id=str(uuid4()),
            event_id=EVENT_ID,
            workshop_id="w1",
            actor_id=OWNER_ID,
            field="location",
            old_value="La Cuisine",
            new_value="Salle B",
            notification_scope="workshop",
            sequence=1,
            created_at=web_clock(),
        )
        session.add(legacy)
        session.flush()
        for user_id in CASCADE:
            attach_change(
                session, legacy, user_id, "Ancien ciblage en cascade", web_clock(), 60
            )
    web_clock.advance(60)
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    scheduler.tick()
    assert {m.recipient for m in scheduler.mailer.messages} == {
        "demo-alice@example.test",
        "demo-sofia@example.test",
    }
    with seeded_db.sessions() as session:
        for n in session.scalars(
            select(Notification).where(Notification.user_id.in_(CASCADE - DIRECT))
        ):
            assert n.status == "skipped" and not n.message
        assert session.scalar(
            select(NotificationChange).where(NotificationChange.active.is_(False))
        )


@pytest.mark.parametrize(
    "changes,expected,spared",
    [
        ({"location": "Salle B"}, 2, 6),
        ({"ends_at": "2026-10-22T15:10"}, 4, 4),
        ({"status": "cancelled"}, 4, 4),
        ({"location": "Salle B", "ends_at": "2026-10-22T15:10"}, 4, 4),
    ],
)
def test_preview_confirm_and_send_share_policy(
    seeded_db, web_settings, web_clock, changes, expected, spared
):
    from app.workshops.routes import workshop_values

    with seeded_db.transaction() as session:
        session.get(User, OWNER_ID).password_hash = HASHED
    app = create_app(web_settings, clock=web_clock)
    with TestClient(app) as client:
        login(client)
        path = f"/organisateur/evenements/{EVENT_ID}/ateliers/w1/modifier"
        page = client.get(path)
        with seeded_db.sessions() as session:
            values = workshop_values(session.get(Workshop, "w1"))
        form = {
            **values,
            **changes,
            "csrf_token": hidden(page, "csrf_token"),
            "revision": hidden(page, "revision"),
            "operation_id": hidden(page, "operation_id"),
            "action": "preview",
        }
        response = client.post(path, data=form)
        assert response.status_code == 200, response.text
        assert f"{expected} destinataire(s) unique(s)" in response.text
        assert f"{spared} personne(s) épargnée(s)" in response.text
        if "location" in changes:
            assert "Lieu</strong> : 2 personne(s)" in response.text
        if "ends_at" in changes:
            assert "Fin</strong> : 4 personne(s)" in response.text
        form["action"] = "confirm"
        assert client.post(path, data=form, follow_redirects=False).status_code == 303
        assert len(groups(seeded_db)) == expected
        web_clock.advance(60)
        app.state.scheduler.tick()
        # Débit par défaut 2/s : laisser passer la deuxième paire si nécessaire.
        web_clock.advance(1)
        app.state.scheduler.tick()
        assert len(app.state.mailer.messages) == expected
