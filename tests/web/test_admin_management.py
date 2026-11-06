"""Le compte de gestion ne peut pas devenir participant, même par accès direct."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth.security import AuthError, digest
from app.auth.services import bootstrap_admin
from app.impact import audience
from app.mailer import MemoryMailer, compose_message
from app.models import (
    AuthSession,
    Contact,
    Enrollment,
    Event,
    Invitation,
    InvitationResponse,
    MailDelivery,
    Participation,
    ParticipationRequest,
    User,
)
from app.participation.services import (
    decide_request,
    invitation_action,
    validate_enrollments,
)
from app.seeds import EVENT_ID, OWNER_ID, SECOND_EVENT_ID
from app.web import create_app
from app.worker import Scheduler
from tests.web.test_events import HASHED, PASSWORD, hidden, login


@pytest.fixture
def management(seeded_db, web_settings, web_clock):
    admin = bootstrap_admin(
        seeded_db, web_settings, "admin@example.test", "Gestion", PASSWORD, web_clock()
    )
    with seeded_db.transaction() as session:
        for user_id in (OWNER_ID, "demo-alice"):
            session.get(User, user_id).password_hash = HASHED
    with TestClient(create_app(web_settings, clock=web_clock)) as client:
        login(client, admin.email)
        yield client, admin


def public_path(database):
    with database.sessions() as session:
        return "/events/" + session.get(Event, SECOND_EVENT_ID).slug


def assert_no_admin_participation(database, admin):
    with database.sessions() as session:
        for model in (Participation, ParticipationRequest, Enrollment):
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.user_id == admin.id)
                )
                == 0
            )


def test_admin_has_management_navigation_and_cannot_open_participant_pages(
    management, seeded_db
):
    client, admin = management
    page = client.get("/admin")
    assert page.status_code == 200
    assert 'href="http://testserver/admin"' in page.text
    assert 'href="http://testserver/espace"' not in page.text
    event_path = public_path(seeded_db)
    assert "Demander à participer" not in client.get(event_path).text
    for path in (
        "/espace",
        "/espace/notifications",
        "/espace/notifications/etat",
        f"/espace/evenements/{EVENT_ID}/ateliers",
        event_path + "/demander",
        "/invitations",
    ):
        response = client.get(path)
        assert response.status_code == 403, path
        assert "réservé à la gestion" in response.text
        assert 'href="/admin"' in response.text
    # L’administration reste utilisable, y compris ses mutations protégées.
    response = client.post(
        "/admin/invitations",
        data={
            "csrf_token": hidden(page, "csrf_token"),
            "email": "gestionnaire@example.test",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert_no_admin_participation(seeded_db, admin)


def test_direct_participant_posts_refuse_admin_with_valid_csrf(management, seeded_db):
    client, admin = management
    nonce = hidden(client.get("/admin"), "csrf_token")
    for path, fields in (
        (public_path(seeded_db) + "/demander", {}),
        (f"/espace/evenements/{EVENT_ID}/ateliers", {"workshop_ids": ["w1"]}),
        ("/espace/notifications/historical/lire", {}),
    ):
        response = client.post(path, data={"csrf_token": nonce, **fields})
        assert response.status_code == 403, path
    assert_no_admin_participation(seeded_db, admin)


def test_admin_not_invitable_even_with_unlinked_contact_and_forged_form(
    management, seeded_db
):
    client, admin = management
    with seeded_db.transaction() as session:
        contact = session.scalar(select(Contact).where(Contact.email == admin.email))
        contact_id = contact.id
        contact.user_id = None  # Un ancien carnet peut ne pas encore avoir le lien.
        session.add(
            Contact(id="ordinary-contact", name="Invité", email="invite@example.test")
        )
    logout_nonce = hidden(client.get("/admin"), "csrf_token")
    client.post("/deconnexion", data={"csrf_token": logout_nonce})
    login(client)
    path = f"/organisateur/evenements/{EVENT_ID}/invitations"
    page = client.get(path)
    assert admin.email not in page.text
    with seeded_db.sessions() as session:
        before = session.scalar(select(func.count()).select_from(Invitation))
    response = client.post(
        path,
        data={
            "csrf_token": hidden(page, "csrf_token"),
            "contact_ids": ["ordinary-contact", contact_id],
        },
    )
    assert response.status_code == 403
    with seeded_db.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Invitation)) == before
        assert session.scalar(select(func.count()).select_from(MailDelivery)) == 0
    assert_no_admin_participation(seeded_db, admin)


@pytest.mark.parametrize("authenticated", [False, True])
def test_admin_email_cannot_get_public_participation_request(
    management, seeded_db, authenticated
):
    client, admin = management
    if not authenticated:
        client.post(
            "/deconnexion",
            data={"csrf_token": hidden(client.get("/admin"), "csrf_token")},
        )
    page = client.get(
        "/admin" if authenticated else public_path(seeded_db) + "/demander"
    )
    response = client.post(
        public_path(seeded_db) + "/demander",
        data={
            "csrf_token": hidden(page, "csrf_token"),
            "email": admin.email,
            "name": admin.name,
        },
    )
    assert response.status_code == (403 if authenticated else 200)
    if not authenticated:
        assert "Votre demande a été prise en compte" in response.text
    with seeded_db.sessions() as session:
        assert (
            session.scalar(select(Invitation).where(Invitation.email == admin.email))
            is None
        )
        assert session.scalar(select(func.count()).select_from(MailDelivery)) == 0
    assert_no_admin_participation(seeded_db, admin)


@pytest.mark.parametrize("recipient_admin", [False, True])
@pytest.mark.parametrize("action", ["accept", "decline"])
def test_old_invitation_cannot_be_used_by_or_for_admin(
    management, seeded_db, web_settings, web_clock, recipient_admin, action
):
    client, admin = management
    if recipient_admin:
        client.post(
            "/deconnexion",
            data={"csrf_token": hidden(client.get("/admin"), "csrf_token")},
        )
    page = client.get("/invitations" if recipient_admin else "/admin")
    nonce = (
        hidden(page, "csrf_token")
        if not recipient_admin
        else page.text.split('id="invitation-csrf" value="')[1].split('"')[0]
    )
    with seeded_db.transaction() as session:
        session.add(
            Invitation(
                id="old-invitation",
                event_id=EVENT_ID,
                email=admin.email if recipient_admin else "legacy-person@example.test",
                inviter_id=OWNER_ID,
                token_digest=digest("old-token"),
                status="pending",
                created_at=web_clock(),
                expires_at=web_clock() + timedelta(hours=1),
            )
        )
        session.flush()
        record = session.get(
            AuthSession, digest(client.cookies.get(web_settings.cookie_name))
        )
        record.pending_event_invitation_id = "old-invitation"
    prepared = client.post(
        "/invitations/preparer", data={"csrf_token": nonce, "token": "old-token"}
    )
    assert prepared.status_code == 403
    response = client.post("/invitations", data={"csrf_token": nonce, "action": action})
    assert response.status_code == 403
    with seeded_db.sessions() as session:
        assert session.get(Invitation, "old-invitation").status == "pending"
        assert (
            session.scalar(
                select(func.count())
                .select_from(InvitationResponse)
                .where(InvitationResponse.invitation_id == "old-invitation")
            )
            == 0
        )
        assert (
            session.scalar(
                select(User).where(User.email == "legacy-person@example.test")
            )
            is None
        )
    assert_no_admin_participation(seeded_db, admin)


def test_old_request_cannot_be_approved_and_admin_cannot_enroll(
    management, seeded_db, web_settings, web_clock
):
    _, admin = management
    with seeded_db.transaction() as session:
        session.add(
            ParticipationRequest(
                event_id=SECOND_EVENT_ID, user_id=admin.id, status="pending"
            )
        )
    with (
        pytest.raises(AuthError, match="réservé à la gestion"),
        seeded_db.transaction() as session,
    ):
        decide_request(
            session,
            web_settings,
            SECOND_EVENT_ID,
            "demo-lea",
            admin.id,
            True,
            web_clock(),
        )
    with seeded_db.sessions() as session:
        assert (
            session.get(ParticipationRequest, (SECOND_EVENT_ID, admin.id)).status
            == "pending"
        )
        assert session.get(Participation, (SECOND_EVENT_ID, admin.id)) is None
        with pytest.raises(AuthError, match="réservé à la gestion"):
            validate_enrollments(
                session, session.get(Event, EVENT_ID), admin.id, ["w1"]
            )


@pytest.mark.parametrize(
    "email", ["demo-alice@example.test", "demo-thomas@example.test"]
)
def test_personal_and_organizer_accounts_keep_participant_access(
    management, seeded_db, email
):
    client, _ = management
    client.post(
        "/deconnexion", data={"csrf_token": hidden(client.get("/admin"), "csrf_token")}
    )
    login(client, email)
    assert client.get("/espace").status_code == 200
    assert client.get("/espace/notifications").status_code == 200
    page = client.get(public_path(seeded_db))
    assert "Demander à participer" in page.text
    request = client.get(public_path(seeded_db) + "/demander")
    response = client.post(
        public_path(seeded_db) + "/demander",
        data={"csrf_token": hidden(request, "csrf_token")},
    )
    assert response.status_code == 200


def test_admin_is_excluded_from_audience_even_with_old_participation(
    management, seeded_db
):
    _, admin = management
    with seeded_db.transaction() as session:
        session.add(
            Participation(event_id=EVENT_ID, user_id=admin.id, status="confirmed")
        )
        session.flush()
        session.add(
            Enrollment(
                event_id=EVENT_ID, user_id=admin.id, workshop_id="w1", status="active"
            )
        )
    with seeded_db.sessions() as session:
        assert admin.id not in {user.id for user in audience(session, EVENT_ID).users}
        assert admin.id not in {
            user.id for user in audience(session, EVENT_ID, "w1").users
        }


@pytest.mark.parametrize("linked", [False, True])
def test_old_admin_invitation_cannot_be_resent_or_sent_from_queue(
    management, seeded_db, web_settings, web_clock, linked
):
    _, admin = management
    with seeded_db.transaction() as session:
        session.add(
            Invitation(
                id="queued-admin-invite",
                event_id=EVENT_ID,
                email=admin.email,
                user_id=admin.id if linked else None,
                inviter_id=OWNER_ID,
                token_digest=digest("queued-token"),
                status="pending",
                created_at=web_clock(),
                expires_at=web_clock() + timedelta(hours=1),
            )
        )
        session.flush()
        session.add(
            MailDelivery(
                id="queued-admin-mail",
                event_id=EVENT_ID,
                event_invitation_id="queued-admin-invite",
                user_id=admin.id if linked else None,
                kind="event_invitation",
                recipient=admin.email,
                backend="memory",
                status="pending",
                created_at=web_clock(),
            )
        )
    with (
        pytest.raises(AuthError, match="réservé à la gestion"),
        seeded_db.transaction() as session,
    ):
        invitation_action(
            session,
            web_settings,
            EVENT_ID,
            OWNER_ID,
            "queued-admin-invite",
            "resend",
            web_clock(),
        )
    mailer = MemoryMailer()
    scheduler = Scheduler(seeded_db, web_settings, mailer, web_clock)
    scheduler.submit(
        "queued-admin-mail",
        compose_message(
            web_settings,
            "queued-admin-mail",
            admin.email,
            "event_invitation",
            event_name="Événement",
            url="http://127.0.0.1:8000/invitations#invitation=queued-token",
            expires=(web_clock() + timedelta(hours=1)).isoformat(),
        ),
    )
    scheduler.tick()
    assert not mailer.messages
    with seeded_db.sessions() as session:
        delivery = session.get(MailDelivery, "queued-admin-mail")
        assert delivery.status == "failed" and delivery.attempted_at is None
        assert delivery.error_code == "no_longer_relevant"
        assert session.get(Invitation, "queued-admin-invite").status == "pending"
