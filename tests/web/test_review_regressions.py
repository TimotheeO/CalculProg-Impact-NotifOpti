"""Cas révélés par la revue avant versionnement : cohérence et révocation."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.auth import routes as auth_routes
from app.auth.security import digest
from app.auth.services import bootstrap_admin, create_invitation
from app.events.services import EventData, revision, update_event, workshops_for
from app.mailer import MemoryMailer
from app.models import (
    AuthSession,
    Enrollment,
    Event,
    MailDelivery,
    Notification,
    OrganizerInvitation,
    User,
    Workshop,
)
from app.notification_groups import recalculate_pending
from app.seeds import EVENT_ID, OWNER_ID
from app.web import create_app
from app.workshops.services import update_workshop, workshop_revision
from app.workshops.types import snapshot
from tests.web.test_auth import PASSWORD as ADMIN_PASSWORD
from tests.web.test_auth import csrf
from tests.web.test_auth import login as admin_login
from tests.web.test_cycle1 import change, groups, worker


def test_global_date_shift_replaces_pending_workshop_dates(
    seeded_db, web_settings, web_clock
):
    change(seeded_db, web_clock, ends_at="2026-10-22T15:10")
    web_clock.advance(10)
    with seeded_db.transaction(immediate=True) as session:
        event = session.get(Event, EVENT_ID)
        data = EventData(
            event.name,
            event.description,
            event.location,
            event.starts_at + timedelta(days=1),
            event.ends_at + timedelta(days=1),
            event.participation_mode,
        )
        update_event(
            session,
            EVENT_ID,
            OWNER_ID,
            data,
            revision(event, workshops_for(session, EVENT_ID)),
            web_clock(),
            operation_id=str(uuid4()),
        )
    web_clock.advance(60)
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    scheduler.tick()
    assert len(scheduler.mailer.messages) == 8
    alice = next(
        message
        for message in scheduler.mailer.messages
        if message.recipient == "demo-alice@example.test"
    )
    workshop_lines = [
        line
        for line in alice.text.splitlines()
        if line.startswith(("Cuisine de saison —", "Dégustation partagée —"))
        and ("début :" in line or "fin :" in line)
    ]
    assert workshop_lines
    assert all("23/10/2026" in line.split("→", 1)[1] for line in workshop_lines)
    assert "Lina" not in alice.text


@pytest.mark.parametrize("delay", [60, 61])
def test_recipient_joining_after_deadline_gets_one_complete_message(
    seeded_db, web_settings, web_clock, delay
):
    change(seeded_db, web_clock, ends_at="2026-10-22T15:10")
    web_clock.advance(delay)
    with seeded_db.transaction(immediate=True) as session:
        session.add(
            Enrollment(
                event_id=EVENT_ID,
                user_id="demo-nora",
                workshop_id="w2",
                status="active",
            )
        )
        session.flush()
        recalculate_pending(session, web_clock(), 60)
    assert len([row for row in groups(seeded_db) if row.user_id == "demo-nora"]) == 1
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    scheduler.tick()
    messages = [
        message
        for message in scheduler.mailer.messages
        if message.recipient == "demo-nora@example.test"
    ]
    assert len(messages) == 1
    assert "début :" in messages[0].text and "fin :" in messages[0].text


def test_zero_window_groups_fields_of_one_confirmation(
    seeded_db, web_settings, web_clock
):
    with seeded_db.transaction(immediate=True) as session:
        event, workshop = session.get(Event, EVENT_ID), session.get(Workshop, "w1")
        update_workshop(
            session,
            EVENT_ID,
            "w1",
            OWNER_ID,
            replace(
                snapshot(workshop), location="Salle B", description="Description B"
            ),
            workshop_revision(session, event),
            web_clock(),
            operation_id=str(uuid4()),
            window=0,
        )
    assert len(groups(seeded_db)) == 2
    scheduler = worker(
        seeded_db,
        web_settings,
        web_clock,
        batch_window_seconds=0,
        send_max_per_period=100,
    )
    scheduler.tick()
    assert len(scheduler.mailer.messages) == 2
    assert all(
        "Salle B" in message.text and "Description B" in message.text
        for message in scheduler.mailer.messages
    )


def test_zero_window_keeps_distinct_confirmations_separate(
    seeded_db, web_settings, web_clock
):
    for fields in ({"location": "Salle B"}, {"description": "Description B"}):
        with seeded_db.transaction(immediate=True) as session:
            event = session.get(Event, EVENT_ID)
            workshop = session.get(Workshop, "w1")
            update_workshop(
                session,
                EVENT_ID,
                "w1",
                OWNER_ID,
                replace(snapshot(workshop), **fields),
                workshop_revision(session, event),
                web_clock(),
                operation_id=str(uuid4()),
                window=0,
            )
    assert len(groups(seeded_db)) == 4
    scheduler = worker(
        seeded_db,
        web_settings,
        web_clock,
        batch_window_seconds=0,
        send_max_per_period=100,
    )
    scheduler.tick()
    assert len(scheduler.mailer.messages) == 4
    assert all(
        ("Salle B" in message.text) != ("Description B" in message.text)
        for message in scheduler.mailer.messages
    )


@pytest.mark.parametrize("action", ["invite", "revoke", "disable"])
def test_admin_session_revoked_during_request_cannot_mutate(
    seeded_db, web_settings, web_clock, monkeypatch, action
):
    admin = bootstrap_admin(
        seeded_db,
        web_settings,
        "admin@example.test",
        "Admin",
        ADMIN_PASSWORD,
        web_clock(),
    )
    with seeded_db.transaction(immediate=True) as session:
        invitation, _, _ = create_invitation(
            session, web_settings, admin.id, "organisateur@example.test", web_clock()
        )
        invitation_id = invitation.id
    with TestClient(create_app(web_settings, clock=web_clock)) as client:
        assert admin_login(client).status_code == 303
        nonce = csrf(client.get("/admin"))
        session_digest = digest(client.cookies.get(web_settings.cookie_name))
        original = auth_routes.form_context

        def revoke_after_initial_check(request, identity, form):
            original(request, identity, form)
            with seeded_db.transaction(immediate=True) as session:
                session.execute(
                    delete(AuthSession).where(
                        AuthSession.token_digest == session_digest
                    )
                )

        monkeypatch.setattr(auth_routes, "form_context", revoke_after_initial_check)
        path = {
            "invite": "/admin/invitations",
            "revoke": f"/admin/invitations/{invitation_id}/revoquer",
            "disable": f"/admin/organisateurs/{OWNER_ID}/desactiver",
        }[action]
        response = client.post(
            path,
            data={"csrf_token": nonce, "email": "autre@example.test"},
            follow_redirects=False,
        )
        assert response.status_code == 403
    with seeded_db.sessions() as session:
        assert (
            session.scalar(select(func.count()).select_from(OrganizerInvitation)) == 1
        )
        assert session.get(OrganizerInvitation, invitation_id).status == "pending"
        assert session.get(User, OWNER_ID).is_active


def test_response_to_request_not_sent_after_account_disabled(
    seeded_db, web_settings, web_clock
):
    from app.participation.services import decide_request

    with seeded_db.transaction(immediate=True) as session:
        deliveries = decide_request(
            session,
            web_settings,
            "demo-fabrique",
            "demo-lea",
            "demo-chloe",
            True,
            web_clock(),
        )
    memory = MemoryMailer()

    class DeferredMailer:
        def send(self, message):
            return memory.send(message)

    scheduler = worker(seeded_db, web_settings, web_clock, mailer=DeferredMailer())
    for delivery_id, message in deliveries:
        scheduler.submit(delivery_id, message)
    with seeded_db.transaction(immediate=True) as session:
        session.get(User, "demo-chloe").is_active = False
    scheduler.tick()
    assert not memory.messages
    with seeded_db.sessions() as session:
        assert (
            session.get(MailDelivery, deliveries[0][0]).error_code
            == "no_longer_relevant"
        )
        assert (
            session.scalar(
                select(Notification).where(Notification.user_id == "demo-chloe")
            )
            is None
        )
