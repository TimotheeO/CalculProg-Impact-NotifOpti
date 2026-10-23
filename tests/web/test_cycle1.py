"""Recette métier du cycle : sécurité, graphe, fenêtres et tentative unique."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth.security import digest
from app.events.services import EventError, revision, workshops_for
from app.impact import audience
from app.journal import snapshot
from app.mailer import MailResult, MemoryMailer
from app.models import (
    Change,
    Contact,
    Enrollment,
    Event,
    Invitation,
    MailDelivery,
    Notification,
    Participation,
    ParticipationRequest,
    User,
    Workshop,
)
from app.participation.services import (
    create_invitations,
    invitation_action,
)
from app.seeds import EVENT_ID, OWNER_ID, SECOND_EVENT_ID
from app.web import create_app
from app.worker import Scheduler
from app.workshops.services import (
    change_dependency,
    update_workshop,
    validate_workshop,
    workshop_revision,
)
from tests.web.test_events import HASHED, NOW, PASSWORD, hidden, login


def change(database, web_clock, workshop_id="w1", **overrides):
    from app.events.services import PARIS

    with database.transaction(immediate=True) as session:
        workshop = session.get(Workshop, workshop_id)
        fields = {
            name: getattr(workshop, name)
            for name in (
                "name",
                "description",
                "location",
                "starts_at",
                "ends_at",
                "capacity",
                "status",
            )
        }
        for field in ("starts_at", "ends_at"):
            fields[field] = fields[field].astimezone(PARIS).strftime("%Y-%m-%dT%H:%M")
        fields["capacity"] = str(fields["capacity"]) if fields["capacity"] else ""
        fields.update(overrides)
        data = validate_workshop(fields)
        event = session.get(Event, EVENT_ID)
        update_workshop(
            session,
            EVENT_ID,
            workshop_id,
            OWNER_ID,
            data,
            workshop_revision(session, event),
            web_clock(),
            operation_id=str(uuid4()),
        )


def groups(database):
    with database.sessions() as session:
        return list(
            session.scalars(
                select(Notification)
                .where(Notification.due_at.is_not(None))
                .order_by(Notification.created_at, Notification.id)
            )
        )


def worker(database, settings, web_clock, mailer=None, **overrides):
    return Scheduler(
        database, replace(settings, **overrides), mailer or MemoryMailer(), web_clock
    )


def test_bfs_diamond_unique_spared_and_global_no_workshop(seeded_db):
    with seeded_db.sessions() as session:
        scoped = audience(session, EVENT_ID, "w1")
        assert {u.id for u in scoped.users} == {
            "demo-alice",
            "demo-sofia",
            "demo-mehdi",
            "demo-lina",
        }
        assert len(scoped.spared) == 4
        assert {w.id for w in scoped.workshops} == {"w1", "w2", "w3"}
        assert "directe" in scoped.reasons["demo-alice"]
        assert "Cascade" in scoped.reasons["demo-lina"]
        assert len(audience(session, EVENT_ID).users) == 8


def test_fixed_window_t0_t50_emits_at60_merges_and_counts(
    seeded_db, web_settings, web_clock
):
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    change(seeded_db, web_clock, location="Salle B")
    scheduler.tick()
    web_clock.advance(50)
    change(seeded_db, web_clock, location="Salle C")
    scheduler.tick()
    assert len(groups(seeded_db)) == 2
    assert all(n.due_at == NOW + timedelta(seconds=60) for n in groups(seeded_db))
    assert not scheduler.mailer.messages
    web_clock.advance(9.9)
    scheduler.tick()
    assert not scheduler.mailer.messages
    web_clock.advance(0.1)
    scheduler.tick()
    assert len(scheduler.mailer.messages) == 2
    assert all(
        "Salle C" in m.text and "Salle B" not in m.text
        for m in scheduler.mailer.messages
    )
    scheduler.tick()
    assert len(scheduler.mailer.messages) == 2
    with seeded_db.sessions() as session:
        _, _, stats = snapshot(session, event_id=EVENT_ID)
        assert stats == {"naive": 4, "final": 2, "saved": 2, "closed": 2}
        assert (
            session.scalar(
                select(func.count())
                .select_from(Change)
                .where(Change.notification_scope == "workshop")
            )
            == 2
        )


def test_return_to_baseline_keeps_history_without_email(
    seeded_db, web_settings, web_clock
):
    scheduler = worker(seeded_db, web_settings, web_clock)
    change(seeded_db, web_clock, location="Salle B")
    web_clock.advance(20)
    change(seeded_db, web_clock, location="La Cuisine")
    web_clock.advance(40)
    scheduler.tick()
    assert not scheduler.mailer.messages
    assert all(n.status == "skipped" and not n.message for n in groups(seeded_db))
    with seeded_db.sessions() as session:
        assert snapshot(session, event_id=EVENT_ID)[2]["saved"] == 4


@pytest.mark.parametrize(
    "base,dependent", [("w1", "w1"), ("w3", "w1"), ("w1", "fabrique-photo")]
)
def test_dependencies_reject_cycles_self_and_cross_event(
    seeded_db, web_clock, base, dependent
):
    with pytest.raises(EventError), seeded_db.transaction(immediate=True) as session:
        change_dependency(
            session, EVENT_ID, OWNER_ID, base, dependent, False, web_clock(), 60
        )


def test_link_edits_do_not_retroactively_apply_or_undo_confirmed_schedule(
    seeded_db, web_settings, web_clock
):
    change(seeded_db, web_clock, ends_at="2026-10-22T15:10")
    web_clock.advance(25)
    with seeded_db.transaction(immediate=True) as session:
        change_dependency(
            session, EVENT_ID, OWNER_ID, "w1", "w4", False, web_clock(), 60
        )
    assert len(groups(seeded_db)) == 4
    assert {n.due_at for n in groups(seeded_db)} == {NOW + timedelta(seconds=60)}
    with seeded_db.transaction(immediate=True) as session:
        change_dependency(
            session, EVENT_ID, OWNER_ID, "w1", "w4", True, web_clock(), 60
        )
    web_clock.advance(35)
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    scheduler.tick()
    assert len(scheduler.mailer.messages) == 4
    with seeded_db.sessions() as session:
        assert session.get(Workshop, "w4").starts_at == NOW + timedelta(hours=3)
        assert session.get(Workshop, "w2").starts_at == NOW + timedelta(
            hours=4, minutes=10
        )


def test_rate_limit_and_priority_apply_globally(seeded_db, web_settings, web_clock):
    change(seeded_db, web_clock, location="Salle mineure")
    change(seeded_db, web_clock, "w4", status="cancelled")
    web_clock.advance(60)
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=1)
    scheduler.tick()
    assert len(scheduler.mailer.messages) == 1
    assert "annulé" in scheduler.mailer.messages[0].text
    scheduler.tick()
    assert len(scheduler.mailer.messages) == 1
    web_clock.advance(1)
    scheduler.tick()
    assert len(scheduler.mailer.messages) == 2
    assert "annulé" in scheduler.mailer.messages[1].text


def test_pending_quota_rechecks_enrollment_before_send(
    seeded_db, web_settings, web_clock
):
    change(seeded_db, web_clock, location="Salle B")
    with seeded_db.transaction(immediate=True) as session:
        session.get(Participation, (EVENT_ID, "demo-alice")).status = "withdrawn"
    web_clock.advance(60)
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    scheduler.tick()
    assert len(scheduler.mailer.messages) == 1
    assert "demo-alice@example.test" not in {
        m.recipient for m in scheduler.mailer.messages
    }


@pytest.mark.parametrize("outcome", ["failed", "uncertain", "raise"])
def test_single_attempt_and_internal_message_survives_transport_error(
    seeded_db, web_settings, web_clock, outcome
):
    class BrokenMailer:
        calls = 0

        def send(self, message):
            self.calls += 1
            if outcome == "raise":
                raise OSError("do not expose transport details")
            return MailResult(outcome, error_code="test_transport")

    mailer = BrokenMailer()
    change(seeded_db, web_clock, location="Salle B")
    web_clock.advance(60)
    scheduler = worker(
        seeded_db, web_settings, web_clock, mailer=mailer, send_max_per_period=100
    )
    scheduler.tick()
    scheduler.tick()
    web_clock.advance(120)
    scheduler.tick()
    assert mailer.calls == 2
    assert all(
        n.status == ("uncertain" if outcome == "raise" else outcome) and n.message
        for n in groups(seeded_db)
    )


def make_invitation(
    database,
    settings,
    web_clock,
    email="nouveau@example.test",
    name="Nouvelle Personne",
):
    with database.transaction(immediate=True) as session:
        contact = Contact(id=str(uuid4()), name=name, email=email)
        session.add(contact)
        session.flush()
        deliveries, _ = create_invitations(
            session, settings, EVENT_ID, OWNER_ID, [contact.id], ["w1"], web_clock()
        )
    return deliveries[0][1].invitation_url.split("invitation=")[1]


def prepare(client, token):
    page = client.get("/invitations")
    import re

    nonce = re.search(r'id="invitation-csrf" value="([^"]+)"', page.text)[1]
    return client.post(
        "/invitations/preparer", data={"csrf_token": nonce, "token": token}
    )


def accept(client, **overrides):
    page = client.get("/invitations")
    fields = {
        "csrf_token": hidden(page, "csrf_token"),
        "action": "accept",
        "name": "Nouvelle Personne",
        "password": PASSWORD,
        "password_confirmation": PASSWORD,
        "workshop_ids": ["w1", "w2"],
        **overrides,
    }
    return client.post("/invitations", data=fields, follow_redirects=False)


def test_link_get_has_no_response_accept_creates_account_and_atomic_choices(
    seeded_db, web_settings, web_clock
):
    token = make_invitation(seeded_db, web_settings, web_clock)
    with TestClient(create_app(web_settings, clock=web_clock)) as client:
        assert client.get("/invitations#invitation=" + token).status_code == 200
        assert prepare(client, token).status_code == 200
        assert client.get("/invitations").status_code == 200
        with seeded_db.sessions() as session:
            assert (
                session.scalar(select(User).where(User.email == "nouveau@example.test"))
                is None
            )
        assert accept(client, role="super_admin").status_code == 303
        with seeded_db.sessions() as session:
            user = session.scalar(
                select(User).where(User.email == "nouveau@example.test")
            )
            assert user.role == "participant" and user.password_hash != PASSWORD
            assert session.get(Participation, (EVENT_ID, user.id)).status == "confirmed"
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(Enrollment)
                    .where(Enrollment.user_id == user.id, Enrollment.status == "active")
                )
                == 2
            )
        assert prepare(client, token).status_code == 410
        assert client.get("/espace").status_code == 200
        assert client.get("/espace/notifications").status_code == 200


def test_refusal_creates_no_account_participation_or_enrollment(
    seeded_db, web_settings, web_clock
):
    token = make_invitation(seeded_db, web_settings, web_clock)
    with TestClient(create_app(web_settings, clock=web_clock)) as client:
        prepare(client, token)
        nonce = hidden(client.get("/invitations"), "csrf_token")
        assert (
            client.post(
                "/invitations", data={"csrf_token": nonce, "action": "decline"}
            ).status_code
            == 200
        )
    with seeded_db.sessions() as session:
        assert (
            session.scalar(select(User).where(User.email == "nouveau@example.test"))
            is None
        )
        assert (
            session.scalar(
                select(Invitation).where(Invitation.token_digest == digest(token))
            ).status
            == "declined"
        )


def test_invalid_capacity_rolls_back_account_and_acceptance(
    seeded_db, web_settings, web_clock
):
    with seeded_db.transaction() as session:
        session.get(Workshop, "w1").capacity = 2
    token = make_invitation(seeded_db, web_settings, web_clock)
    with TestClient(create_app(web_settings, clock=web_clock)) as client:
        prepare(client, token)
        assert accept(client).status_code == 409
    with seeded_db.sessions() as session:
        assert (
            session.scalar(select(User).where(User.email == "nouveau@example.test"))
            is None
        )
        assert (
            session.scalar(
                select(Invitation).where(Invitation.token_digest == digest(token))
            ).status
            == "pending"
        )


def test_existing_account_requires_login_keeps_password_and_role(
    seeded_db, web_settings, web_clock
):
    with seeded_db.transaction() as session:
        user = session.get(User, "demo-lea")
        user.password_hash = HASHED
        user.role = "organizer"
        contact = session.scalar(select(Contact).where(Contact.user_id == user.id))
        (_,) = create_invitations(
            session, web_settings, EVENT_ID, OWNER_ID, [contact.id], [], web_clock()
        )[0]
        token = _[1].invitation_url.split("invitation=")[1]
    with TestClient(create_app(web_settings, clock=web_clock)) as client:
        prepare(client, token)
        assert "Se connecter au compte destinataire" in client.get("/invitations").text
        assert accept(client).status_code == 403
        login(client, "demo-lea@example.test")
        assert accept(client, workshop_ids=[]).status_code == 303
    with seeded_db.sessions() as session:
        user = session.get(User, "demo-lea")
        assert user.password_hash == HASHED and user.role == "organizer"


def test_contact_and_event_routes_scoped_and_csrf_protected(
    seeded_db, web_settings, web_clock
):
    with seeded_db.transaction() as session:
        session.get(User, OWNER_ID).password_hash = HASHED
    with TestClient(create_app(web_settings, clock=web_clock)) as client:
        login(client)
        for path in [
            "/organisateur/contacts",
            f"/organisateur/evenements/{EVENT_ID}/invitations",
            f"/organisateur/evenements/{EVENT_ID}/journal",
            f"/organisateur/evenements/{EVENT_ID}/dependances",
            f"/organisateur/evenements/{EVENT_ID}/ateliers/w1",
        ]:
            assert client.get(path).status_code == 200, path
        assert (
            client.get(
                f"/organisateur/evenements/{SECOND_EVENT_ID}/journal"
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/organisateur/contacts", data={"name": "X", "email": "x@example.test"}
            ).status_code
            == 403
        )


def test_request_unverified_pending_and_declined_reserve_no_places(
    seeded_db, web_settings, web_clock
):
    with seeded_db.transaction() as session:
        session.get(Event, EVENT_ID).participation_mode = "open"
    app = create_app(web_settings, clock=web_clock)
    with TestClient(app) as client:
        # Utiliser le slug réel de la fixture plutôt qu’un chemin présumé.
        with seeded_db.sessions() as session:
            slug = session.get(Event, EVENT_ID).slug
        path = f"/events/{slug}/demander"
        nonce = hidden(client.get(path), "csrf_token")
        response = client.post(
            path,
            data={
                "csrf_token": nonce,
                "email": "demande@example.test",
                "name": "Personne Demandante",
            },
        )
        assert response.status_code == 200, response.text
        assert len(app.state.mailer.messages) == 1
        with seeded_db.sessions() as session:
            assert (
                session.scalar(select(User).where(User.email == "demande@example.test"))
                is None
            )
        token = app.state.mailer.messages[0].invitation_url.split("invitation=")[1]
        prepare(client, token)
        assert accept(client).status_code == 303
        with seeded_db.sessions() as session:
            user = session.scalar(
                select(User).where(User.email == "demande@example.test")
            )
            assert session.get(Participation, (EVENT_ID, user.id)) is None
            assert (
                session.get(ParticipationRequest, (EVENT_ID, user.id)).status
                == "pending"
            )


def test_workshop_http_create_preview_confirm_replay_and_error(
    seeded_db, web_settings, web_clock
):
    with seeded_db.transaction() as session:
        session.get(User, OWNER_ID).password_hash = HASHED
    with TestClient(create_app(web_settings, clock=web_clock)) as client:
        login(client)
        path = f"/organisateur/evenements/{EVENT_ID}/ateliers/nouveau"
        page = client.get(path)
        fields = {
            "csrf_token": hidden(page, "csrf_token"),
            "creation_id": hidden(page, "creation_id"),
            "name": "Atelier test",
            "description": "",
            "location": "Salle test",
            "starts_at": "2026-10-22T17:00",
            "ends_at": "2026-10-22T17:30",
            "capacity": "",
            "status": "active",
        }
        response = client.post(path, data=fields, follow_redirects=False)
        assert response.status_code == 303, response.text
        assert (
            client.post(path, data=fields, follow_redirects=False).headers["location"]
            == response.headers["location"]
        )
        edit = f"/organisateur/evenements/{EVENT_ID}/ateliers/w1/modifier"
        page = client.get(edit)
        fields = {
            "csrf_token": hidden(page, "csrf_token"),
            "revision": hidden(page, "revision"),
            "operation_id": hidden(page, "operation_id"),
            "action": "preview",
            "name": "Cuisine de saison",
            "description": "",
            "location": "Salle B",
            "starts_at": "2026-10-22T14:00",
            "ends_at": "2026-10-22T15:00",
            "capacity": "12",
            "status": "active",
        }
        preview = client.post(edit, data=fields)
        assert (
            preview.status_code == 200 and "2 destinataire(s) unique(s)" in preview.text
        )
        fields["action"] = "confirm"
        assert client.post(edit, data=fields, follow_redirects=False).status_code == 303
        assert client.post(edit, data=fields, follow_redirects=False).status_code == 303
        assert len(groups(seeded_db)) == 2
        fields["location"] = "Autre lieu"
        assert client.post(edit, data=fields, follow_redirects=False).status_code == 409
        fields["capacity"] = "1"
        assert client.post(edit, data=fields, follow_redirects=False).status_code in {
            409,
            422,
        }


def test_concurrent_last_seat_acceptance_is_atomic(seeded_db, web_settings, web_clock):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    with seeded_db.transaction() as session:
        session.get(
            Workshop, "w1"
        ).capacity = 3  # deux inscriptions existantes, une place libre
    tokens = [
        make_invitation(
            seeded_db, web_settings, web_clock, email=f"concurrent{i}@example.test"
        )
        for i in range(2)
    ]

    # Une application se construit au démarrage, avant les requêtes concurrentes.
    # Ne pas faire concourir les fabriques de schémas Pydantic du harnais de test.
    applications = [create_app(web_settings, clock=web_clock) for _ in tokens]
    simultaneous = Barrier(2)

    def attempt(item):
        app, token = item
        with TestClient(app) as client:
            assert prepare(client, token).status_code == 200
            simultaneous.wait(timeout=10)
            return accept(client, workshop_ids=["w1"]).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, zip(applications, tokens, strict=True))) == [
            303,
            409,
        ]
    with seeded_db.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Enrollment)
                .where(Enrollment.workshop_id == "w1", Enrollment.status == "active")
            )
            == 3
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(User)
                .where(User.email.like("concurrent%"))
            )
            == 1
        )


def test_expired_revoked_and_replaced_invitation_links_rejected(
    seeded_db, web_settings, web_clock
):
    token = make_invitation(seeded_db, web_settings, web_clock)
    with seeded_db.transaction(immediate=True) as session:
        invitation = session.scalar(
            select(Invitation).where(Invitation.token_digest == digest(token))
        )
        operation_id = str(uuid4())
        deliveries = invitation_action(
            session,
            web_settings,
            EVENT_ID,
            OWNER_ID,
            invitation.id,
            "resend",
            web_clock(),
            operation_id,
        )
        assert len(deliveries) == 1
        assert (
            invitation_action(
                session,
                web_settings,
                EVENT_ID,
                OWNER_ID,
                invitation.id,
                "resend",
                web_clock(),
                operation_id,
            )
            == []
        )
        newtoken = deliveries[0][1].invitation_url.split("invitation=")[1]
    with TestClient(create_app(web_settings, clock=web_clock)) as client:
        assert prepare(client, token).status_code == 410
        assert prepare(client, newtoken).status_code == 200
        web_clock.advance(49 * 3600)
        assert prepare(client, newtoken).status_code == 410
    with seeded_db.transaction(immediate=True) as session:
        invitation_action(
            session,
            web_settings,
            EVENT_ID,
            OWNER_ID,
            invitation.id,
            "revoke",
            web_clock(),
        )
    with TestClient(create_app(web_settings, clock=web_clock)) as client:
        assert prepare(client, newtoken).status_code == 410


def test_request_approval_refusal_idempotence_and_no_ghost_membership(
    seeded_db, web_settings, web_clock
):
    from app.participation.services import decide_request

    with seeded_db.transaction(immediate=True) as session:
        pending = session.get(ParticipationRequest, (EVENT_ID, "demo-chloe"))
        if pending is None:
            session.add(
                ParticipationRequest(
                    event_id=EVENT_ID, user_id="demo-chloe", status="pending"
                )
            )
        session.flush()
        mails = decide_request(
            session, web_settings, EVENT_ID, OWNER_ID, "demo-chloe", False, web_clock()
        )
        assert len(mails) == 1
        assert (
            decide_request(
                session,
                web_settings,
                EVENT_ID,
                OWNER_ID,
                "demo-chloe",
                False,
                web_clock(),
            )
            == []
        )
        assert session.get(Participation, (EVENT_ID, "demo-chloe")) is None
        session.add(
            ParticipationRequest(
                event_id=EVENT_ID, user_id="demo-lea", status="pending"
            )
        )
        session.flush()
        assert (
            len(
                decide_request(
                    session,
                    web_settings,
                    EVENT_ID,
                    OWNER_ID,
                    "demo-lea",
                    True,
                    web_clock(),
                )
            )
            == 1
        )
        session.flush()
        assert session.get(Participation, (EVENT_ID, "demo-lea")).status == "confirmed"
        assert (
            session.scalar(select(Enrollment).where(Enrollment.user_id == "demo-lea"))
            is None
        )


def test_adjacent_allowed_overlap_and_cross_event_blocked(seeded_db):
    from app.participation.services import validate_enrollments

    with seeded_db.transaction() as session:
        event = session.get(Event, EVENT_ID)
        assert (
            len(validate_enrollments(session, event, "demo-sofia", ["w1", "w2"])) == 2
        )
        with pytest.raises(EventError, match="chevauche"):
            validate_enrollments(session, event, "demo-sofia", ["w1", "w4"])
        with pytest.raises(EventError, match="autre événement"):
            validate_enrollments(session, event, "demo-sofia", ["fabrique-photo"])
        other = session.get(Workshop, "fabrique-photo")
        first = session.get(Workshop, "w1")
        other.starts_at, other.ends_at = first.starts_at, first.ends_at
        with pytest.raises(EventError, match="chevauche"):
            validate_enrollments(session, event, "demo-alex", ["w1"])


def test_daily_limit_and_new_scheduler_preserve_recent_rate_usage(
    seeded_db, web_settings, web_clock
):
    change(seeded_db, web_clock, location="Salle B")
    web_clock.advance(60)
    first = worker(seeded_db, web_settings, web_clock, send_max_per_period=1)
    first.tick()
    assert len(first.mailer.messages) == 1
    second = worker(
        seeded_db, web_settings, web_clock, send_max_per_period=1, send_daily_limit=1
    )
    second.tick()
    assert not second.mailer.messages
    web_clock.advance(2)
    second.tick()
    assert not second.mailer.messages
    third = worker(seeded_db, web_settings, web_clock, send_max_per_period=1)
    third.tick()
    assert len(third.mailer.messages) == 1


def test_worker_lock_and_interrupted_attempt_never_retried(
    seeded_db, web_settings, web_clock
):
    first = worker(seeded_db, web_settings, web_clock, worker_enabled=True)
    second = worker(seeded_db, web_settings, web_clock, worker_enabled=True)
    try:
        first.start()
        with pytest.raises(RuntimeError, match="ordonnanceur"):
            second.start()
    finally:
        first.close()
        second.close()
    change(seeded_db, web_clock, location="Salle B")
    web_clock.advance(60)
    scheduler = worker(
        seeded_db, web_settings, web_clock, worker_enabled=True, send_max_per_period=100
    )
    scheduler._prepare_groups()
    with seeded_db.transaction() as session:
        row = session.scalar(
            select(MailDelivery).where(MailDelivery.notification_id.is_not(None))
        )
        row.status = "sending"
        notification_id = row.notification_id
        session.get(Notification, notification_id).status = "sending"
    try:
        scheduler.start()
    finally:
        scheduler.close()
    with seeded_db.sessions() as session:
        assert session.get(Notification, notification_id).status == "uncertain"


@pytest.mark.parametrize(
    "kind",
    [
        "organizer_invitation",
        "event_invitation",
        "request_verification",
        "request_response",
        "notification",
        "cancellation",
        "password_reset",
    ],
)
def test_french_email_templates_escape_html_and_have_plain_text(web_settings, kind):
    from app.mailer import compose_message

    message = compose_message(
        web_settings,
        "id",
        "personne@example.test",
        kind,
        event_name="<script>titre</script>",
        content="<b>nouvelle salle</b>",
        reason="Cascade",
        url="http://127.0.0.1:8000/invitations#invitation=secret",
    )
    assert "<script>titre</script>" not in message.html
    assert "&lt;script&gt;titre&lt;/script&gt;" in message.html
    assert message.text.strip() and message.subject
    assert "secret" not in repr(message)


def test_smtp_mailpit_message_is_multipart_and_uncertain_not_retried(
    web_settings, monkeypatch
):
    import smtplib

    from app.mailer import MailpitMailer, compose_message

    messages = []

    class SMTP:
        def __init__(self, host, port, timeout):
            assert host == "127.0.0.1" and port == 1025 and timeout == 10

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def send_message(self, message):
            messages.append(message)
            return {}

    monkeypatch.setattr(smtplib, "SMTP", SMTP)
    message = compose_message(
        web_settings,
        "id",
        "personne@example.test",
        "notification",
        event_name="Atelier",
        content="Salle C",
        reason="Cascade",
    )
    result = MailpitMailer(web_settings).send(message)
    assert result.status == "accepted"
    assert messages[0].get_body(preferencelist=("plain",))
    assert messages[0].get_body(preferencelist=("html",))
    assert "Salle C" in messages[0].get_body(preferencelist=("plain",)).get_content()

    def broken(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(smtplib, "SMTP", broken)
    assert MailpitMailer(web_settings).send(message).status == "uncertain"


def test_three_changes_six_people_eighteen_requests_six_messages(
    seeded_db, web_settings, web_clock
):
    with seeded_db.transaction(immediate=True) as session:
        change_dependency(
            session, EVENT_ID, OWNER_ID, "w1", "w4", False, web_clock(), 60
        )
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    for index, end in enumerate(["15:10", "15:20", "15:30"]):
        if index:
            web_clock.advance(20)
        change(seeded_db, web_clock, ends_at=f"2026-10-22T{end}")
        scheduler.tick()
    with seeded_db.sessions() as session:
        assert snapshot(session, event_id=EVENT_ID)[2]["saved"] == 0
    web_clock.advance(20)
    scheduler.tick()
    assert len(scheduler.mailer.messages) == 6
    with seeded_db.sessions() as session:
        assert snapshot(session, event_id=EVENT_ID)[2] == {
            "naive": 18,
            "final": 6,
            "saved": 12,
            "closed": 6,
        }


def test_link_added_after_confirmation_applies_to_next_change_only(
    seeded_db, web_settings, web_clock
):
    with seeded_db.transaction() as session:
        session.get(Participation, (EVENT_ID, "demo-emma")).status = "withdrawn"
    change(seeded_db, web_clock, "w6", ends_at="2026-10-22T15:10")
    assert not groups(seeded_db)
    web_clock.advance(20)
    with seeded_db.transaction(immediate=True) as session:
        change_dependency(
            session, EVENT_ID, OWNER_ID, "w6", "w1", False, web_clock(), 60
        )
    assert not groups(seeded_db)
    change(seeded_db, web_clock, "w6", status="cancelled")
    assert len(groups(seeded_db)) == 4


def test_cancel_one_workshop_preserves_other_pending_workshop(
    seeded_db, web_settings, web_clock
):
    with seeded_db.transaction() as session:
        session.add(
            Enrollment(
                event_id=EVENT_ID,
                user_id="demo-alice",
                workshop_id="w4",
                status="active",
            )
        )
    change(seeded_db, web_clock, location="Lieu devenu caduc")
    change(seeded_db, web_clock, "w2", location="Autre lieu caduc")
    change(seeded_db, web_clock, "w4", location="Lieu à conserver")
    change(seeded_db, web_clock, status="cancelled")
    web_clock.advance(60)
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    scheduler.tick()
    alice = next(
        m for m in scheduler.mailer.messages if m.recipient == "demo-alice@example.test"
    )
    assert "annulé" in alice.text and "Lieu à conserver" in alice.text
    assert "Lieu devenu caduc" not in alice.text
    assert "Autre lieu caduc" not in alice.text
    with seeded_db.sessions() as session:
        assert (
            session.get(Enrollment, (EVENT_ID, "demo-alice", "w1")).status == "active"
        )


def test_unused_draft_workshop_deletion_protected_by_usage(seeded_db, web_clock):
    from app.workshops.services import delete_workshop

    with seeded_db.transaction(immediate=True) as session:
        event = session.get(Event, EVENT_ID)
        with pytest.raises(EventError, match="brouillon"):
            delete_workshop(
                session,
                EVENT_ID,
                "w1",
                OWNER_ID,
                revision(event, workshops_for(session, EVENT_ID)),
                "Cuisine de saison",
                web_clock(),
            )
        event.status = "draft"
        session.flush()
        with pytest.raises(EventError, match="inscriptions"):
            delete_workshop(
                session,
                EVENT_ID,
                "w1",
                OWNER_ID,
                revision(event, workshops_for(session, EVENT_ID)),
                "Cuisine de saison",
                web_clock(),
            )
        fresh = Workshop(
            id="unused",
            event_id=EVENT_ID,
            name="Inutilisé",
            description="",
            location="Salle",
            starts_at=event.starts_at,
            ends_at=event.ends_at,
        )
        session.add(fresh)
        session.flush()
        delete_workshop(
            session,
            EVENT_ID,
            "unused",
            OWNER_ID,
            revision(event, workshops_for(session, EVENT_ID)),
            "Inutilisé",
            web_clock(),
        )
    with seeded_db.sessions() as session:
        assert session.get(Workshop, "unused") is None
        assert session.get(Workshop, "w1") is not None


def test_retarget_older_change_keeps_earliest_deadline(
    seeded_db, web_settings, web_clock
):
    # Nora ouvre son groupe à t=20, puis s’inscrit à un atelier modifié à t=0.
    change(seeded_db, web_clock, ends_at="2026-10-22T15:10")
    web_clock.advance(20)
    change(seeded_db, web_clock, "w4", location="Poterie B")
    web_clock.advance(10)
    with seeded_db.transaction(immediate=True) as session:
        from app.notification_groups import recalculate_pending

        session.add(
            Enrollment(
                event_id=EVENT_ID,
                user_id="demo-nora",
                workshop_id="w1",
                status="active",
            )
        )
        session.flush()
        recalculate_pending(session, web_clock(), 60)
    nora = next(n for n in groups(seeded_db) if n.user_id == "demo-nora")
    assert nora.opened_at == NOW and nora.due_at == NOW + timedelta(seconds=60)
    web_clock.advance(30)
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    scheduler.tick()
    message = next(
        m for m in scheduler.mailer.messages if m.recipient == "demo-nora@example.test"
    )
    assert "15 h 10" in message.text and "Poterie B" in message.text
