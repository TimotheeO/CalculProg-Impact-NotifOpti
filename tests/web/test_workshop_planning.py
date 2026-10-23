"""Conséquences réelles : marges, prérequis, atomicité et contenu ciblé."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.events.services import EventError, parse_local, workshops_for
from app.models import (
    Change,
    Enrollment,
    Event,
    EventAction,
    EventOperation,
    Notification,
    User,
    Workshop,
)
from app.seeds import EVENT_ID, OWNER_ID
from app.web import create_app
from app.workshops.planning import plan_change
from app.workshops.services import (
    change_dependency,
    preview_workshop,
    update_workshop,
    workshop_revision,
)
from app.workshops.types import WorkshopData, snapshot
from tests.web.test_cycle1 import change, groups, worker
from tests.web.test_events import HASHED, hidden, login


def node(key, start, end, status="active"):
    data = WorkshopData(
        key,
        "",
        "Salle",
        parse_local(f"2026-10-22T{start}"),
        parse_local(f"2026-10-22T{end}"),
        None,
        status,
    )
    return SimpleNamespace(id=key, **data.__dict__)


def edges(*pairs):
    return [
        SimpleNamespace(base_workshop_id=a, dependent_workshop_id=b) for a, b in pairs
    ]


@pytest.mark.parametrize(
    "start,end,expected",
    [
        ("15:00", "16:00", "15:30"),  # Aucun battement : tout le retard.
        ("15:15", "16:15", "15:30"),  # Quinze minutes absorbées.
        ("15:30", "16:30", None),  # Égalité : aucun chevauchement.
        ("16:00", "17:00", None),  # Une heure de marge.
    ],
)
def test_delay_consumes_margin_and_preserves_duration(start, end, expected):
    a, b = node("a", "14:00", "15:00"), node("b", start, end)
    proposed = replace(
        snapshot(a),
        starts_at=a.starts_at + timedelta(minutes=30),
        ends_at=a.ends_at + timedelta(minutes=30),
    )
    plan = plan_change([a, b], edges(("a", "b")), "a", proposed)
    if expected is None:
        assert [row.workshop_id for row in plan.changes] == ["a"]
        assert plan.spared == ("b",)
    else:
        row = plan.changes[1]
        assert row.workshop_id == "b" and row.automatic
        assert row.after.starts_at == parse_local(f"2026-10-22T{expected}")
        assert row.after.ends_at - row.after.starts_at == b.ends_at - b.starts_at
    assert b.starts_at == parse_local(f"2026-10-22T{start}")  # Calcul sans mutation.


def test_diamond_uses_latest_parent_once_including_external_prerequisite():
    a, b, c, d, external = [
        node("a", "14:00", "15:00"),
        node("b", "15:00", "16:00"),
        node("c", "15:00", "16:30"),
        node("d", "16:30", "17:30"),
        node("external", "14:00", "17:15"),
    ]
    plan = plan_change(
        [a, b, c, d, external],
        edges(("a", "b"), ("a", "c"), ("b", "d"), ("c", "d"), ("external", "d")),
        "a",
        replace(snapshot(a), ends_at=a.ends_at + timedelta(minutes=30)),
    )
    rows = {row.workshop_id: row for row in plan.changes}
    assert len(plan.changes) == 4
    assert rows["d"].after.starts_at == external.ends_at
    assert rows["d"].after.ends_at == parse_local("2026-10-22T18:15")


def test_margin_stops_branch_and_does_not_repair_unrelated_old_schedule():
    a, b, c = (
        node("a", "14:00", "15:00"),
        node("b", "16:00", "17:00"),
        node("c", "16:00", "17:00"),
    )
    plan = plan_change(
        [a, b, c],
        edges(("a", "b"), ("b", "c")),
        "a",
        replace(snapshot(a), ends_at=a.ends_at + timedelta(minutes=30)),
    )
    assert [row.workshop_id for row in plan.changes] == ["a"]
    assert plan.spared == ("b", "c")


@pytest.mark.parametrize(
    "field,value",
    [
        ("ends_at", parse_local("2026-10-22T14:45")),
        ("starts_at", parse_local("2026-10-22T14:10")),
        ("location", "Autre salle"),
    ],
)
def test_earlier_finish_later_start_only_or_room_does_not_move_dependents(field, value):
    a, b = node("a", "14:00", "15:00"), node("b", "15:00", "16:00")
    plan = plan_change(
        [a, b], edges(("a", "b")), "a", replace(snapshot(a), **{field: value})
    )
    assert [row.workshop_id for row in plan.changes] == ["a"]


def test_cancellation_traverses_already_cancelled_node_and_preserves_independent():
    a, b, c, d = (
        node("a", "14:00", "15:00"),
        node("b", "15:00", "16:00", "cancelled"),
        node("c", "16:00", "17:00"),
        node("d", "14:00", "15:00"),
    )
    plan = plan_change(
        [a, b, c, d],
        edges(("a", "b"), ("b", "c")),
        "a",
        replace(snapshot(a), status="cancelled"),
    )
    assert {row.workshop_id for row in plan.changes} == {"a", "c"}
    assert all(row.after.status == "cancelled" for row in plan.changes)
    assert plan.spared == ("b",) and d.status == "active"


def test_malformed_cycle_fails_without_mutation():
    a, b = node("a", "14:00", "15:00"), node("b", "15:00", "16:00")
    with pytest.raises(EventError, match="boucle") as error:
        plan_change(
            [a, b],
            edges(("a", "b"), ("b", "a")),
            "a",
            replace(snapshot(a), status="cancelled"),
        )
    assert error.value.status == 409 and a.status == b.status == "active"


def test_source_cannot_start_before_its_prerequisite_finishes():
    a, b = node("a", "14:00", "15:00"), node("b", "15:00", "16:00")
    with pytest.raises(EventError, match="prérequis"):
        plan_change(
            [a, b],
            edges(("a", "b")),
            "b",
            replace(snapshot(b), starts_at=parse_local("2026-10-22T14:45")),
        )


@pytest.mark.parametrize(
    "start,end,moved", [("14:15", "15:45", False), ("14:45", "16:15", True)]
)
def test_real_margin_controls_persistence_and_recipients(
    seeded_db, web_settings, web_clock, start, end, moved
):
    change(
        seeded_db,
        web_clock,
        "w4",
        starts_at=f"2026-10-22T{start}",
        ends_at=f"2026-10-22T{end}",
    )
    assert {n.user_id for n in groups(seeded_db)} == (
        {"demo-nora", "demo-hugo"} if moved else {"demo-nora"}
    )
    with seeded_db.sessions() as session:
        dependent = session.get(Workshop, "w5")
        assert dependent.starts_at == parse_local(
            f"2026-10-22T{'16:15' if moved else '16:00'}"
        )
        assert dependent.ends_at == parse_local(
            f"2026-10-22T{'17:15' if moved else '17:00'}"
        )
    web_clock.advance(60)
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    scheduler.tick()
    if moved:
        hugo = next(
            m
            for m in scheduler.mailer.messages
            if m.recipient == "demo-hugo@example.test"
        )
        assert (
            "16 h 15" in hugo.text
            and "17 h 15" in hugo.text
            and "après « Initiation à la poterie" in hugo.text
        )
        assert "14 h 45" not in hugo.text
    else:
        assert [m.recipient for m in scheduler.mailer.messages] == [
            "demo-nora@example.test"
        ]


def test_cancel_really_cancels_descendants_and_keeps_enrollments(
    seeded_db, web_settings, web_clock
):
    with seeded_db.sessions() as session:
        before = list(
            session.execute(
                select(Enrollment.workshop_id, Enrollment.user_id, Enrollment.status)
            )
        )
    change(seeded_db, web_clock, status="cancelled")
    with seeded_db.sessions() as session:
        assert {
            w.id for w in workshops_for(session, EVENT_ID) if w.status == "cancelled"
        } == {"w1", "w2", "w3"}
        assert (
            list(
                session.execute(
                    select(
                        Enrollment.workshop_id, Enrollment.user_id, Enrollment.status
                    )
                )
            )
            == before
        )
        assert (
            len(
                list(
                    session.scalars(
                        select(EventAction).where(
                            EventAction.kind == "workshop_cascade_applied"
                        )
                    )
                )
            )
            == 2
        )
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    web_clock.advance(60)  # Départ anticipé réservé au cycle 2.
    scheduler.tick()
    assert len(scheduler.mailer.messages) == 4
    lina = next(
        m for m in scheduler.mailer.messages if m.recipient == "demo-lina@example.test"
    )
    assert "Accords" in lina.text and "actif → annulé" in lina.text
    assert "Dégustation partagée — état" not in lina.text


def test_out_of_event_cascade_rolls_back_entire_operation(seeded_db, web_clock):
    models = (Change, EventAction, EventOperation, Notification)
    with seeded_db.sessions() as session:
        initial = {
            m: session.scalar(select(func.count()).select_from(m)) for m in models
        }
        times = {w.id: snapshot(w) for w in workshops_for(session, EVENT_ID)}
    with pytest.raises(EventError, match="hors du programme"):
        change(seeded_db, web_clock, ends_at="2026-10-22T16:10")
    with seeded_db.sessions() as session:
        assert {w.id: snapshot(w) for w in workshops_for(session, EVENT_ID)} == times
        assert {
            m: session.scalar(select(func.count()).select_from(m)) for m in models
        } == initial


def test_preview_is_readonly_confirmation_idempotent_and_link_removal_keeps_actual_changes(
    seeded_db, web_clock
):
    with seeded_db.transaction(immediate=True) as session:
        event, source = session.get(Event, EVENT_ID), session.get(Workshop, "w1")
        before = {w.id: snapshot(w) for w in workshops_for(session, EVENT_ID)}
        expected = workshop_revision(session, event)
        data = replace(snapshot(source), ends_at=source.ends_at + timedelta(minutes=30))
        plan = preview_workshop(session, EVENT_ID, "w1", OWNER_ID, data, expected)[2]
        assert len(plan.changes) == 3
        assert {w.id: snapshot(w) for w in workshops_for(session, EVENT_ID)} == before
        operation_id = str(uuid4())
        for _ in range(2):
            update_workshop(
                session,
                EVENT_ID,
                "w1",
                OWNER_ID,
                data,
                expected,
                web_clock(),
                operation_id=operation_id,
            )
    with seeded_db.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Change)
                .where(Change.operation_id == operation_id)
            )
            == 5
        )
        assert session.get(Workshop, "w3").ends_at == parse_local("2026-10-22T17:30")
    with seeded_db.transaction(immediate=True) as session:
        change_dependency(
            session, EVENT_ID, OWNER_ID, "w2", "w3", True, web_clock(), 60
        )
        change_dependency(
            session, EVENT_ID, OWNER_ID, "w1", "w3", True, web_clock(), 60
        )
    assert {n.user_id for n in groups(seeded_db)} == {
        "demo-alice",
        "demo-sofia",
        "demo-mehdi",
        "demo-lina",
    }


def test_graph_edit_after_preview_requires_review_and_does_not_mutate_workshops(
    seeded_db, web_clock
):
    with seeded_db.sessions() as session:
        expected = workshop_revision(session, session.get(Event, EVENT_ID))
        before = {w.id: snapshot(w) for w in workshops_for(session, EVENT_ID)}
    with seeded_db.transaction(immediate=True) as session:
        change_dependency(
            session, EVENT_ID, OWNER_ID, "w1", "w4", False, web_clock(), 60
        )
    with (
        pytest.raises(EventError, match="dépendances ont changé") as error,
        seeded_db.transaction(immediate=True) as session,
    ):
        update_workshop(
            session,
            EVENT_ID,
            "w1",
            OWNER_ID,
            replace(before["w1"], status="cancelled"),
            expected,
            web_clock(),
        )
    assert error.value.status == 409
    with seeded_db.sessions() as session:
        assert {w.id: snapshot(w) for w in workshops_for(session, EVENT_ID)} == before


@pytest.mark.parametrize(
    "workshop_id,changes,label",
    [
        ("w1", {"ends_at": "2026-10-22T15:30"}, "Conséquences sur le programme"),
        ("w4", {"ends_at": "2026-10-22T15:45"}, "Ateliers dépendants inchangés"),
        ("w1", {"status": "cancelled"}, "Actif → Annulé"),
    ],
)
def test_http_preview_explains_actual_plan_without_false_conflicts(
    seeded_db, web_settings, web_clock, workshop_id, changes, label
):
    from app.workshops.routes import workshop_values

    with seeded_db.transaction() as session:
        session.get(User, OWNER_ID).password_hash = HASHED
        values = workshop_values(session.get(Workshop, workshop_id))
    with TestClient(create_app(web_settings, clock=web_clock)) as client:
        login(client)
        path = f"/organisateur/evenements/{EVENT_ID}/ateliers/{workshop_id}/modifier"
        page = client.get(path)
        form = {
            **values,
            **changes,
            **{
                key: hidden(page, key)
                for key in ("csrf_token", "revision", "operation_id")
            },
            "action": "preview",
        }
        response = client.post(path, data=form)
        assert response.status_code == 200, response.text
        assert label in response.text
        assert "Conflits à signaler" not in response.text
        with seeded_db.sessions() as session:
            assert workshop_values(session.get(Workshop, workshop_id)) == values
        form["action"] = "confirm"
        assert client.post(path, data=form, follow_redirects=False).status_code == 303
