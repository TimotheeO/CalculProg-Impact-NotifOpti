"""Exports protégés, archives, graphe, sauvegardes et débit sans envoi externe."""

import csv
import io
import sqlite3
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.backup import copy_database
from app.dashboard import graph_data
from app.database import Database
from app.events.services import (
    cancel_event,
    revision,
    workshops_for,
)
from app.mailer import MemoryMailer
from app.models import Event, MailAttempt, MailDelivery, User
from app.seeds import EVENT_ID, OWNER_ID, SECOND_EVENT_ID
from app.web import create_app
from app.worker import Scheduler
from tests.web.test_cycle1_migrations import migrate
from tests.web.test_events import HASHED, hidden, login


@pytest.fixture
def organizer_cycle2(seeded_db, web_settings, web_clock):
    with seeded_db.transaction() as session:
        session.get(User, OWNER_ID).password_hash = HASHED
        session.get(User, "demo-alice").password_hash = HASHED
    with TestClient(create_app(web_settings, clock=web_clock)) as client:
        login(client)
        yield client


def test_dashboard_counts_and_graph_are_real_and_scoped(organizer_cycle2, seeded_db):
    page = organizer_cycle2.get(f"/organisateur/evenements/{EVENT_ID}/tableau-de-bord")
    assert page.status_code == 200 and "data-impact-graph=" in page.text
    assert "Participants confirmés" in page.text and "Dépendances" in page.text
    with seeded_db.sessions() as session:
        graph = graph_data(session, EVENT_ID)
        assert len(graph["nodes"]) == 6 and len(graph["edges"]) == 4
        positions = {n["id"]: n["x"] for n in graph["nodes"]}
        assert positions["w1"] < positions["w2"] < positions["w3"]
    assert (
        organizer_cycle2.get(
            f"/organisateur/evenements/{SECOND_EVENT_ID}/tableau-de-bord"
        ).status_code
        == 404
    )


def test_participant_filters_csv_accents_and_formula_neutralization(
    organizer_cycle2, seeded_db
):
    with seeded_db.transaction() as session:
        session.get(User, "demo-alice").name = '=HYPERLINK("attaque")'
    base = f"/organisateur/evenements/{EVENT_ID}"
    page = organizer_cycle2.get(
        base + "/participants?q=sofia&atelier=w1&statut=confirmed"
    )
    assert page.status_code == 200 and "Sofia" in page.text
    assert "demo-mehdi@example.test" not in page.text
    for kind in ("participants", "inscriptions", "reponses"):
        response = organizer_cycle2.get(base + "/export.csv?type=" + kind)
        assert response.status_code == 200 and response.content.startswith(
            b"\xef\xbb\xbf"
        )
        rows = list(
            csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";")
        )
        assert len(rows) > 1 and "attachment" in response.headers["content-disposition"]
        assert "no-store" in response.headers["cache-control"]
        if kind != "reponses":
            assert any(row[0].startswith("'=HYPERLINK") for row in rows[1:])
    assert (
        organizer_cycle2.get(base + "/participants?atelier=foreign").status_code == 404
    )
    assert (
        organizer_cycle2.get(
            f"/organisateur/evenements/{SECOND_EVENT_ID}/export.csv"
        ).status_code
        == 404
    )
    assert organizer_cycle2.get(base + "/export.csv?type=unknown").status_code == 422


def test_archive_keeps_history_and_blocks_mutations(
    organizer_cycle2, seeded_db, web_clock
):
    with seeded_db.transaction() as session:
        event = session.get(Event, EVENT_ID)
        cancel_event(
            session,
            EVENT_ID,
            OWNER_ID,
            revision(event, workshops_for(session, EVENT_ID)),
            web_clock(),
        )
    page = organizer_cycle2.get(f"/organisateur/evenements/{EVENT_ID}/etat/archiver")
    with seeded_db.sessions() as session:
        name = session.get(Event, EVENT_ID).name
    response = organizer_cycle2.post(
        f"/organisateur/evenements/{EVENT_ID}/etat/archiver",
        data={
            "csrf_token": hidden(page, "csrf_token"),
            "revision": hidden(page, "revision"),
            "operation_id": hidden(page, "operation_id"),
            "confirmation": name,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with seeded_db.sessions() as session:
        event = session.get(Event, EVENT_ID)
        assert event.status == "archived"
        before = session.scalar(
            text("SELECT count(*) FROM changes WHERE event_id=:id"), {"id": EVENT_ID}
        )
    assert (
        organizer_cycle2.get(
            f"/organisateur/evenements/{EVENT_ID}/participants"
        ).status_code
        == 200
    )
    assert (
        organizer_cycle2.get(
            f"/organisateur/evenements/{EVENT_ID}/export.csv"
        ).status_code
        == 200
    )
    page = organizer_cycle2.get(f"/organisateur/evenements/{EVENT_ID}")
    response = organizer_cycle2.post(
        f"/organisateur/evenements/{EVENT_ID}/dependances",
        data={
            "csrf_token": hidden(page, "csrf_token"),
            "base_id": "w1",
            "dependent_id": "w4",
            "action": "add",
        },
    )
    assert response.status_code == 409
    with seeded_db.sessions() as session:
        assert (
            session.scalar(
                text("SELECT count(*) FROM changes WHERE event_id=:id"),
                {"id": EVENT_ID},
            )
            == before
        )


@pytest.mark.parametrize(
    "value", ["=1+1", "+SUM(A1)", "-2+3", "@SUM(A1)", "\t=1", "\r=1", "  =1"]
)
def test_spreadsheet_cells_cannot_be_formulas(value):
    from app.events.management import spreadsheet_cell

    assert spreadsheet_cell(value).startswith("'")


def test_backup_restore_preserve_data_and_refuse_overwrite(seeded_db, tmp_path):
    backup = tmp_path / "backup.sqlite3"
    restored = tmp_path / "restored.sqlite3"
    copy_database(seeded_db.path, backup)
    copy_database(backup, restored)
    with sqlite3.connect(restored) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] > 0
    assert restored.stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError, match="existe"):
        copy_database(backup, restored)
    db = Database("sqlite:///" + str(restored))
    db.check_schema()
    db.close()


def test_populated_cycle1_upgrade_preserves_program_and_notifications(seeded_db):
    with seeded_db.sessions() as session:
        before = {
            table: session.scalar(text(f"SELECT count(*) FROM {table}"))
            for table in (
                "users",
                "events",
                "workshops",
                "notifications",
                "notification_changes",
            )
        }
    migrate(seeded_db, "downgrade", "0003")
    seeded_db.initialize()
    seeded_db.check_schema()
    with seeded_db.sessions() as session:
        after = {
            table: session.scalar(text(f"SELECT count(*) FROM {table}"))
            for table in before
        }
        assert before == after
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []


def test_sliding_rate_limit_with_105_local_messages_and_worker_restart(
    seeded_db, web_settings, web_clock
):
    settings = replace(
        web_settings, send_max_per_period=5, send_period_seconds=2, send_daily_limit=300
    )
    with seeded_db.transaction() as session:
        for index in range(105):
            session.add(
                MailDelivery(
                    id=str(uuid4()),
                    kind="request_response",
                    recipient=f"test-{index}@example.test",
                    backend="memory",
                    status="pending",
                    created_at=web_clock(),
                    context={
                        "subject": "Test de débit",
                        "html": "<p>Test</p>",
                        "text": "Test",
                    },
                )
            )
    mailer = MemoryMailer()
    scheduler = Scheduler(seeded_db, settings, mailer, web_clock)
    for index in range(45):
        scheduler.tick()
        if index == 10:
            scheduler = Scheduler(seeded_db, settings, mailer, web_clock)
        web_clock.advance(1)
    with seeded_db.sessions() as session:
        attempts = list(
            session.scalars(select(MailAttempt).order_by(MailAttempt.started_at))
        )
        assert len(attempts) == 105
        timestamps = [a.started_at.timestamp() for a in attempts]
        for value in timestamps:
            assert sum(value - 2 < t <= value for t in timestamps) <= 5
        assert (
            session.scalar(
                select(func.count())
                .select_from(MailDelivery)
                .where(MailDelivery.status == "pending")
            )
            == 0
        )


def test_retry_http_is_scoped_and_double_click_keeps_two_attempts(
    organizer_cycle2, seeded_db, web_settings, web_clock
):
    from tests.web.test_cycle1 import change, worker
    from tests.web.test_cycle2_notifications import ControlledMailer

    change(seeded_db, web_clock, "w4", location="Lieu pour échec contrôlé")
    web_clock.advance(60)
    scheduler = worker(seeded_db, web_settings, web_clock, mailer=ControlledMailer())
    scheduler.tick()
    with seeded_db.sessions() as session:
        delivery_id = session.scalar(
            select(MailDelivery.id).where(
                MailDelivery.user_id == "demo-nora", MailDelivery.kind == "notification"
            )
        )
    page = organizer_cycle2.get(f"/organisateur/evenements/{EVENT_ID}/journal")
    fields = {"csrf_token": hidden(page, "csrf_token"), "operation_id": str(uuid4())}
    assert (
        organizer_cycle2.post(
            f"/organisateur/evenements/{SECOND_EVENT_ID}/envois/{delivery_id}/reessayer",
            data=fields,
        ).status_code
        == 404
    )
    path = f"/organisateur/evenements/{EVENT_ID}/envois/{delivery_id}/reessayer"
    for _ in range(2):
        assert (
            organizer_cycle2.post(path, data=fields, follow_redirects=False).status_code
            == 303
        )
    with seeded_db.sessions() as session:
        assert session.get(MailDelivery, delivery_id).status == "simulated"
        assert (
            session.scalar(
                select(func.count())
                .select_from(MailAttempt)
                .where(MailAttempt.delivery_id == delivery_id)
            )
            == 2
        )


def test_verified_public_request_is_not_counted_as_accepted_invitation(
    seeded_db, web_clock
):
    from app.dashboard import counters
    from app.models import Invitation, ParticipationRequest

    with seeded_db.transaction() as session:
        before = counters(session, EVENT_ID, web_clock())
        invitation = session.scalar(
            select(Invitation).where(
                Invitation.event_id == EVENT_ID,
                Invitation.email == "demo-chloe@example.test",
            )
        )
        invitation.purpose, invitation.status = "request", "accepted"
        session.add(
            ParticipationRequest(
                event_id=EVENT_ID, user_id="demo-chloe", status="pending"
            )
        )
    with seeded_db.sessions() as session:
        after = counters(session, EVENT_ID, web_clock())
        assert after["responses"]["accepted"] == before["responses"]["accepted"]
        assert after["requests"]["pending"] == 1
        assert after["confirmed"] == before["confirmed"] == 8
