"""Récupération réelle du compte et contrôle du parcours personnel."""

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth.security import password_matches
from app.models import AuthSession, PasswordReset, User
from app.seeds import EVENT_ID
from app.web import create_app
from tests.web.test_events import HASHED, PASSWORD, hidden, login

NEW_PASSWORD = "Une nouvelle phrase personnelle de test 2026!"


@pytest.fixture
def account_client(seeded_db, web_settings, web_clock):
    with seeded_db.transaction() as session:
        session.get(User, "demo-alice").password_hash = HASHED
        session.get(User, "demo-thomas").password_hash = HASHED
    with TestClient(create_app(web_settings, clock=web_clock)) as client:
        yield client


def request_link(client, email="demo-alice@example.test"):
    page = client.get("/mot-de-passe-oublie")
    response = client.post(
        "/mot-de-passe-oublie",
        data={"csrf_token": hidden(page, "csrf_token"), "email": email},
    )
    assert response.status_code == 200
    return response


def prepare_reset(client, url):
    nonce = (
        client.get("/reinitialisation")
        .text.split('id="invitation-csrf" value="')[1]
        .split('"')[0]
    )
    token = parse_qs(urlsplit(url).fragment)["reset"][0]
    return client.post(
        "/reinitialisation/preparer", data={"csrf_token": nonce, "token": token}
    )


def test_reset_replaces_password_invalidates_old_sessions_and_is_single_use(
    account_client, seeded_db, web_settings
):
    client = account_client
    login(client, "demo-alice@example.test")
    old_cookie = client.cookies.get(web_settings.cookie_name)
    response = request_link(client)
    assert "Si cette adresse correspond" in response.text
    url = client.app.state.mailer.messages[-1].invitation_url
    with seeded_db.sessions() as session:
        row = session.scalar(select(PasswordReset))
        assert parse_qs(urlsplit(url).fragment)["reset"][0] not in row.token_digest
    assert prepare_reset(client, url).status_code == 200
    page = client.get("/reinitialisation")
    response = client.post(
        "/reinitialisation",
        data={
            "csrf_token": hidden(page, "csrf_token"),
            "password": NEW_PASSWORD,
            "password_confirmation": NEW_PASSWORD,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with seeded_db.sessions() as session:
        assert password_matches(
            session.get(User, "demo-alice").password_hash, NEW_PASSWORD
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuthSession)
                .where(AuthSession.user_id == "demo-alice")
            )
            == 0
        )
    client.cookies.set(
        web_settings.cookie_name, old_cookie, domain="testserver.local", path="/"
    )
    assert client.get("/espace", follow_redirects=False).status_code == 303
    client.cookies.clear()
    assert prepare_reset(client, url).status_code == 410
    page = client.get("/connexion")
    response = client.post(
        "/connexion",
        data={
            "csrf_token": hidden(page, "csrf_token"),
            "email": "demo-alice@example.test",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 401
    page = client.get("/connexion")
    response = client.post(
        "/connexion",
        data={
            "csrf_token": hidden(page, "csrf_token"),
            "email": "demo-alice@example.test",
            "password": NEW_PASSWORD,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_unknown_address_has_same_public_response_without_mail(account_client):
    unknown = request_link(account_client, "absent@example.test")
    assert not account_client.app.state.mailer.messages
    known = request_link(account_client)
    assert "Si cette adresse correspond à un compte actif" in unknown.text
    assert "Si cette adresse correspond à un compte actif" in known.text


def test_new_request_invalidates_previous_link_and_expiry_is_enforced(
    account_client, web_clock
):
    request_link(account_client)
    old = account_client.app.state.mailer.messages[-1].invitation_url
    request_link(account_client)
    fresh = account_client.app.state.mailer.messages[-1].invitation_url
    assert old != fresh
    assert prepare_reset(account_client, old).status_code == 410
    assert prepare_reset(account_client, fresh).status_code == 200
    web_clock.advance(1801)
    assert prepare_reset(account_client, fresh).status_code == 410


def test_reset_bad_csrf_mismatch_and_disabled_account_do_not_change_password(
    account_client, seeded_db
):
    request_link(account_client)
    url = account_client.app.state.mailer.messages[-1].invitation_url
    assert prepare_reset(account_client, url).status_code == 200
    page = account_client.get("/reinitialisation")
    for nonce, confirmation, expected in (
        ("wrong", NEW_PASSWORD, 403),
        (hidden(page, "csrf_token"), "different", 422),
    ):
        response = account_client.post(
            "/reinitialisation",
            data={
                "csrf_token": nonce,
                "password": NEW_PASSWORD,
                "password_confirmation": confirmation,
            },
        )
        assert response.status_code == expected
    with seeded_db.transaction() as session:
        user = session.get(User, "demo-alice")
        assert password_matches(user.password_hash, PASSWORD)
        user.is_active = False
    assert prepare_reset(account_client, url).status_code == 410


def test_recovery_is_rate_limited(account_client):
    for _ in range(3):
        request_link(account_client, "absent@example.test")
    page = account_client.get("/mot-de-passe-oublie")
    response = account_client.post(
        "/mot-de-passe-oublie",
        data={"csrf_token": hidden(page, "csrf_token"), "email": "absent@example.test"},
    )
    assert response.status_code == 429


def test_personal_hub_lists_pending_invitation_and_refusal_is_scoped(
    account_client, seeded_db, web_settings, web_clock
):
    from app.models import Contact
    from app.participation.services import create_invitations
    from app.seeds import OWNER_ID

    with seeded_db.transaction() as session:
        contact = session.scalar(
            select(Contact).where(Contact.email == "demo-thomas@example.test")
        )
        create_invitations(
            session, web_settings, EVENT_ID, OWNER_ID, [contact.id], [], web_clock()
        )
    login(account_client)
    page = account_client.get("/espace")
    assert (
        "Invitations en attente" in page.text
        and "Mon planning chronologique" in page.text
    )
    with seeded_db.sessions() as session:
        from app.models import Invitation

        invitation = session.scalar(
            select(Invitation).where(
                Invitation.email == "demo-thomas@example.test",
                Invitation.event_id == EVENT_ID,
            )
        )
    response = account_client.post(
        f"/espace/invitations/{invitation.id}/repondre",
        data={"csrf_token": hidden(page, "csrf_token"), "action": "decline"},
    )
    assert response.status_code == 200
    with seeded_db.sessions() as session:
        assert session.get(Invitation, invitation.id).status == "declined"
    response = account_client.post(
        "/espace/invitations/foreign/repondre",
        data={
            "csrf_token": hidden(account_client.get("/espace"), "csrf_token"),
            "action": "accept",
        },
    )
    assert response.status_code == 410


def test_participant_withdrawal_requires_confirmation_and_valid_session(
    account_client, seeded_db
):
    from uuid import uuid4

    from app.models import Participation

    login(account_client, "demo-alice@example.test")
    nonce = hidden(account_client.get("/espace"), "csrf_token")
    path = f"/espace/evenements/{EVENT_ID}/retirer"
    assert account_client.post(path, data={"csrf_token": nonce}).status_code == 422
    assert (
        account_client.post(
            path, data={"csrf_token": "wrong", "confirmation": "oui"}
        ).status_code
        == 403
    )
    fields = {"csrf_token": nonce, "confirmation": "oui", "operation_id": str(uuid4())}
    for _ in range(2):
        assert (
            account_client.post(path, data=fields, follow_redirects=False).status_code
            == 303
        )
    with seeded_db.sessions() as session:
        assert (
            session.get(Participation, (EVENT_ID, "demo-alice")).status == "withdrawn"
        )


def test_personal_reconfirmation_route_checks_choices_before_activation(
    account_client, seeded_db, web_clock
):
    from app.events.services import (
        cancel_event,
        change_event_state,
        revision,
        workshops_for,
    )
    from app.models import Event, Participation
    from app.seeds import OWNER_ID

    with seeded_db.transaction() as session:
        event = session.get(Event, EVENT_ID)
        cancel_event(
            session,
            EVENT_ID,
            OWNER_ID,
            revision(event, workshops_for(session, EVENT_ID)),
            web_clock(),
        )
        change_event_state(
            session,
            EVENT_ID,
            OWNER_ID,
            "reactiver",
            revision(event, workshops_for(session, EVENT_ID)),
            web_clock(),
        )
    login(account_client, "demo-alice@example.test")
    path = f"/espace/evenements/{EVENT_ID}/reconfirmer"
    page = account_client.get(path)
    assert page.status_code == 200 and "NOUVELLE CONFIRMATION" in page.text
    response = account_client.post(
        path,
        data={"csrf_token": hidden(page, "csrf_token"), "workshop_ids": ["w1", "w4"]},
    )
    assert response.status_code == 409
    with seeded_db.sessions() as session:
        assert (
            session.get(Participation, (EVENT_ID, "demo-alice")).status
            == "pending_confirmation"
        )
    response = account_client.post(
        path,
        data={"csrf_token": hidden(page, "csrf_token"), "workshop_ids": ["w1"]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with seeded_db.sessions() as session:
        assert (
            session.get(Participation, (EVENT_ID, "demo-alice")).status == "confirmed"
        )
