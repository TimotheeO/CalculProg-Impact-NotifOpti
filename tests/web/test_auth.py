import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import cli
from app.auth.security import PASSWORDS, AuthError, digest, password_matches
from app.auth.services import accept_invitation, bootstrap_admin, create_invitation
from app.auth.sessions import new_session
from app.models import AuthSession, Contact, OrganizerInvitation, User
from app.seeds import EVENT_ID, SECOND_EVENT_ID
from app.web import create_app

PASSWORD = "Une phrase fictive pour les tests 42!"
NOW = datetime(2026, 10, 16, 10, tzinfo=timezone.utc)


def csrf(response):
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    if not match:
        match = re.search(r'id="invitation-csrf" value="([^"]+)"', response.text)
    assert match, response.text
    return match[1]


def login(client, email="admin@example.test", password=PASSWORD, **extra):
    token = csrf(client.get("/connexion", follow_redirects=False))
    return client.post(
        "/connexion",
        data={"csrf_token": token, "email": email, "password": password, **extra},
        follow_redirects=False,
    )


def prepare(client, token):
    nonce = csrf(client.get("/activation-organisateur"))
    return client.post(
        "/activation-organisateur/preparer", data={"csrf_token": nonce, "token": token}
    )


def accept(client, **extra):
    nonce = csrf(client.get("/activation-organisateur"))
    return client.post(
        "/activation-organisateur",
        data={
            "csrf_token": nonce,
            "name": "Camille Test",
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
            **extra,
        },
        follow_redirects=False,
    )


@pytest.fixture
def auth(seeded_db, web_settings):
    admin = bootstrap_admin(
        seeded_db, web_settings, "ADMIN@example.test", "Admin Test", PASSWORD, NOW
    )
    clock = [NOW]
    application = create_app(web_settings, clock=lambda: clock[0])
    with TestClient(application) as client:
        yield client, admin, clock


def invite(auth, email="camille@example.test"):
    client, _, _ = auth
    if client.get("/admin", follow_redirects=False).status_code != 200:
        assert login(client).status_code == 303
    nonce = csrf(client.get("/admin"))
    response = client.post(
        "/admin/invitations",
        data={"csrf_token": nonce, "email": email},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    message = client.app.state.mailer.messages[-1]
    token = parse_qs(urlsplit(message.invitation_url).fragment)["invitation"][0]
    return token, message


def logout(client):
    return client.post(
        "/deconnexion",
        data={"csrf_token": csrf(client.get("/espace"))},
        follow_redirects=False,
    )


def test_bootstrap_hashes_password_and_refuses_second_admin(
    auth, seeded_db, web_settings
):
    _, admin, _ = auth
    assert admin.email == "admin@example.test"
    assert admin.password_hash.startswith("$argon2id$")
    assert password_matches(admin.password_hash, PASSWORD)
    assert not password_matches(admin.password_hash, "wrong")
    with pytest.raises(AuthError, match="existe déjà"):
        bootstrap_admin(
            seeded_db, web_settings, "new@example.test", "Admin", PASSWORD, NOW
        )
    with seeded_db.sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(User).where(User.role == "super_admin")
            )
            == 1
        )


def test_bootstrap_does_not_take_over_existing_account(seeded_db, web_settings):
    with pytest.raises(AuthError, match="Aucun rôle"):
        bootstrap_admin(
            seeded_db, web_settings, "demo-alice@example.test", "Admin", PASSWORD, NOW
        )
    with seeded_db.sessions() as session:
        assert session.get(User, "demo-alice").role == "participant"


@pytest.mark.parametrize("password", ["short", " " * 20, "x" * 129])
def test_bootstrap_invalid_password_does_not_create_user(
    database, web_settings, password
):
    with pytest.raises(AuthError):
        bootstrap_admin(
            database, web_settings, "admin@example.test", "Admin", password, NOW
        )
    with database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0


@pytest.mark.parametrize(
    "path",
    [
        "/admin",
        "/organisateur",
        "/espace",
        "/admin/courriers-locaux",
        f"/organisateur/evenements/{EVENT_ID}",
    ],
)
def test_anonymous_private_pages_redirect_to_login(auth, path):
    client, _, _ = auth
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/connexion"


def test_login_rotates_session_and_logout_invalidates_it(auth, seeded_db, web_settings):
    client, admin, _ = auth
    nonce = csrf(client.get("/connexion"))
    old = client.cookies.get(web_settings.cookie_name)
    response = client.post(
        "/connexion",
        data={"csrf_token": nonce, "email": admin.email, "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Secure" not in cookie
    raw = client.cookies.get(web_settings.cookie_name)
    assert raw != old
    with seeded_db.sessions() as session:
        assert session.get(AuthSession, digest(old)) is None
        assert session.get(AuthSession, digest(raw)).user_id == admin.id
    assert client.get("/deconnexion").status_code == 405
    assert client.get("/organisateur").status_code == 403
    assert logout(client).status_code == 303
    client.cookies.set(web_settings.cookie_name, raw)
    assert client.get("/admin", follow_redirects=False).status_code == 303


@pytest.mark.parametrize(
    "email,password",
    [
        ("missing@example.test", PASSWORD),
        ("admin@example.test", "wrong"),
        ("demo-alice@example.test", PASSWORD),
    ],
)
def test_login_uses_same_error_and_never_echoes_password(auth, email, password):
    response = login(auth[0], email, password)
    assert response.status_code == 401
    assert "Adresse e-mail ou mot de passe incorrect" in response.text
    assert password not in response.text


@pytest.mark.parametrize(
    "nonce,origin",
    [
        ("wrong", None),
        ("évil", None),
        (None, None),
        ("valid", "https://evil.example"),
        ("valid", "null"),
    ],
)
def test_login_rejects_csrf_and_foreign_origin(auth, nonce, origin):
    client, _, _ = auth
    actual = csrf(client.get("/connexion"))
    response = client.post(
        "/connexion",
        data={
            "csrf_token": actual if nonce == "valid" else nonce or "",
            "email": "admin@example.test",
            "password": PASSWORD,
        },
        headers={"Origin": origin} if origin else {},
    )
    assert response.status_code == 403


def test_attempt_limit_survives_application_restart_and_expires(auth, web_settings):
    client, _, clock = auth
    for _ in range(5):
        assert login(client, password="wrong").status_code == 401
    response = login(client)
    assert response.status_code == 429 and response.headers["Retry-After"] == "900"
    with TestClient(create_app(web_settings, clock=lambda: clock[0])) as other:
        assert login(other).status_code == 429
        clock[0] += timedelta(minutes=15)
        assert login(other).status_code == 303


def test_session_expiry_is_checked_on_server(auth):
    client, _, clock = auth
    assert login(client).status_code == 303
    clock[0] += timedelta(hours=8)
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_invitation_confirm_creates_exact_role_contact_and_rotates_session(
    auth, seeded_db, web_settings
):
    client, _, _ = auth
    token, message = invite(auth)
    assert token not in repr(message)
    assert "#invitation=" in message.invitation_url
    assert "Simulation locale" in client.get("/admin").text
    assert (
        message.invitation_url.replace("&", "&amp;")
        in client.get("/admin/courriers-locaux").text
    )
    assert logout(client).status_code == 303
    assert prepare(client, token).status_code == 200
    old = client.cookies.get(web_settings.cookie_name)
    with seeded_db.sessions() as session:
        assert (
            session.scalar(select(User).where(User.email == message.recipient)) is None
        )
        invitation = session.scalar(
            select(OrganizerInvitation).where(
                OrganizerInvitation.email == message.recipient
            )
        )
        assert invitation.status == "pending" and invitation.token_digest == digest(
            token
        )
    response = accept(client, role="super_admin")
    assert (
        response.status_code == 303 and response.headers["location"] == "/organisateur"
    )
    assert client.cookies.get(web_settings.cookie_name) != old
    assert "ESPACE ORGANISATEUR" in client.get("/organisateur").text
    assert "ESPACE PARTICIPANT" in client.get("/espace").text
    assert client.get("/admin").status_code == 403
    assert client.get("/admin/courriers-locaux").status_code == 403
    with seeded_db.sessions() as session:
        user = session.scalar(select(User).where(User.email == message.recipient))
        assert user.role == "organizer" and password_matches(
            user.password_hash, PASSWORD
        )
        assert session.scalar(select(Contact).where(Contact.user_id == user.id))
        assert session.get(AuthSession, digest(old)) is None
        invitation = session.get(OrganizerInvitation, invitation.id)
        assert (
            invitation.status == "accepted" and invitation.accepted_user_id == user.id
        )
        assert invitation.accepted_at == NOW
    assert prepare(client, token).status_code == 410


@pytest.mark.parametrize("email", ["invalid", "<script>@", "x@localhost"])
def test_invalid_invitation_email_is_rejected(auth, email):
    client, _, _ = auth
    login(client)
    response = client.post(
        "/admin/invitations",
        data={"csrf_token": csrf(client.get("/admin")), "email": email},
    )
    assert response.status_code == 422
    assert not client.app.state.mailer.messages


def test_duplicate_invitation_and_revocation(auth, seeded_db):
    client, _, _ = auth
    token, _ = invite(auth)
    nonce = csrf(client.get("/admin"))
    assert (
        client.post(
            "/admin/invitations",
            data={"csrf_token": nonce, "email": "CAMILLE@example.test"},
        ).status_code
        == 409
    )
    with seeded_db.sessions() as session:
        invitation = session.scalar(select(OrganizerInvitation))
    assert (
        client.post(
            f"/admin/invitations/{invitation.id}/revoquer", data={"csrf_token": "bad"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/admin/invitations/{invitation.id}/revoquer",
            data={"csrf_token": nonce},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert logout(client).status_code == 303
    assert prepare(client, token).status_code == 410
    with seeded_db.sessions() as session:
        assert session.get(OrganizerInvitation, invitation.id).status == "revoked"


def test_expired_invitation_is_refused_and_can_be_replaced(auth):
    client, _, clock = auth
    token, _ = invite(auth)
    clock[0] += timedelta(hours=48)
    assert prepare(client, token).status_code == 410
    replacement, _ = invite(auth)
    assert replacement != token
    assert prepare(client, replacement).status_code == 200


@pytest.mark.parametrize(
    "extra",
    [
        {"name": " "},
        {"password": "short"},
        {"password_confirmation": "different phrase"},
    ],
)
def test_invalid_activation_does_not_consume_invitation_or_create_account(
    auth, seeded_db, extra
):
    client, _, _ = auth
    token, message = invite(auth)
    logout(client)
    prepare(client, token)
    assert accept(client, **extra).status_code == 422
    with seeded_db.sessions() as session:
        assert (
            session.scalar(select(User).where(User.email == message.recipient)) is None
        )
        assert session.scalar(select(OrganizerInvitation)).status == "pending"


def test_existing_participant_must_login_and_keeps_password_and_participations(
    auth, seeded_db
):
    client, _, _ = auth
    original = PASSWORDS.hash(PASSWORD)
    with seeded_db.transaction() as session:
        session.get(User, "demo-alex").password_hash = original
    token, _ = invite(auth, "demo-alex@example.test")
    logout(client)
    prepare(client, token)
    assert (
        "Connectez-vous avec ce compte" in client.get("/activation-organisateur").text
    )
    assert accept(client).status_code == 403
    assert (
        login(client, "demo-alex@example.test", following="invitation").headers[
            "location"
        ]
        == "/activation-organisateur"
    )
    assert accept(client).status_code == 303
    with seeded_db.sessions() as session:
        assert session.get(User, "demo-alex").password_hash == original
    space = client.get("/espace").text
    assert "Les Rencontres créatives" in space and "La Fabrique du vendredi" in space
    assert "Aucun événement" in client.get("/organisateur").text


def test_owner_and_coorganizer_access_are_event_scoped(auth):
    client, _, _ = auth
    token, _ = invite(auth, "demo-thomas@example.test")
    logout(client)
    prepare(client, token)
    assert accept(client).status_code == 303
    assert client.get(f"/organisateur/evenements/{EVENT_ID}").status_code == 200
    assert client.get(f"/organisateur/evenements/{SECOND_EVENT_ID}").status_code == 404
    logout(client)
    login(client)
    token, _ = invite(auth, "demo-lea@example.test")
    logout(client)
    prepare(client, token)
    accept(client)
    assert client.get(f"/organisateur/evenements/{EVENT_ID}").status_code == 200
    assert client.get(f"/organisateur/evenements/{SECOND_EVENT_ID}").status_code == 200


def test_disabling_revokes_all_sessions_and_reactivation_requires_login(
    auth, web_settings, seeded_db
):
    client, _, _ = auth
    token, message = invite(auth)
    with TestClient(client.app) as organizer:
        prepare(organizer, token)
        accept(organizer)
        raw = organizer.cookies.get(web_settings.cookie_name)
        with seeded_db.sessions() as session:
            user = session.scalar(select(User).where(User.email == message.recipient))
        nonce = csrf(client.get("/admin"))
        path = f"/admin/organisateurs/{user.id}"
        assert (
            client.post(
                f"{path}/desactiver", data={"csrf_token": nonce}, follow_redirects=False
            ).status_code
            == 303
        )
        assert organizer.get("/organisateur", follow_redirects=False).status_code == 303
        assert login(organizer, message.recipient).status_code == 401
        assert (
            client.post(
                f"{path}/reactiver", data={"csrf_token": nonce}, follow_redirects=False
            ).status_code
            == 303
        )
        organizer.cookies.clear()
        organizer.cookies.set(web_settings.cookie_name, raw)
        assert organizer.get("/organisateur", follow_redirects=False).status_code == 303
        organizer.cookies.clear()
        assert login(organizer, message.recipient).status_code == 303


@pytest.mark.parametrize(
    "body,mime,status",
    [
        ("a=1&a=2", "application/x-www-form-urlencoded", 400),
        ("broken", "application/x-www-form-urlencoded", 400),
        ("x=" + "x" * 17000, "application/x-www-form-urlencoded", 413),
        ("{}", "application/json", 415),
        (
            "&".join(f"x{i}=1" for i in range(13)),
            "application/x-www-form-urlencoded",
            400,
        ),
    ],
)
def test_untrusted_form_formats_have_safe_errors(auth, body, mime, status):
    response = auth[0].post("/connexion", content=body, headers={"Content-Type": mime})
    assert response.status_code == status
    assert "Traceback" not in response.text


def test_cli_bootstrap_asks_for_password_without_printing_it(
    database, monkeypatch, capsys
):
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: PASSWORD)
    assert (
        cli.main(
            [
                "--database-url",
                database.url,
                "create-super-admin",
                "--email",
                "admin@example.test",
                "--name",
                "Admin",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert PASSWORD not in captured.out + captured.err
    assert "Super-admin créé" in captured.out


def test_cli_mismatched_confirmation_is_atomic(database, monkeypatch, capsys):
    values = iter([PASSWORD, "different"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: next(values))
    assert (
        cli.main(
            [
                "--database-url",
                database.url,
                "create-super-admin",
                "--email",
                "admin@example.test",
                "--name",
                "Admin",
            ]
        )
        == 2
    )
    assert "ne correspondent pas" in capsys.readouterr().err
    with database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0


def test_concurrent_acceptance_creates_one_account(auth, seeded_db, web_settings):
    from app.auth.services import prepare_invitation

    _, admin, _ = auth
    with seeded_db.transaction(immediate=True) as session:
        invitation, _, raw = create_invitation(
            session, web_settings, admin.id, "concurrent@example.test", NOW
        )
        guest, cookie = new_session(session, web_settings, NOW)
        prepare_invitation(session, guest, raw, NOW)
        form = {
            "csrf_token": guest.csrf_token,
            "name": "Concurrent",
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
        }

    def attempt(_):
        try:
            accept_invitation(seeded_db, web_settings, cookie, form, None, NOW)
            return "accepted"
        except AuthError:
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["accepted", "refused"]
    with seeded_db.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(User)
                .where(User.email == invitation.email)
            )
            == 1
        )
        assert session.get(OrganizerInvitation, invitation.id).status == "accepted"


def test_participant_cannot_enter_or_mutate_other_spaces(auth, seeded_db):
    client, _, _ = auth
    with seeded_db.transaction() as session:
        session.get(User, "demo-alice").password_hash = PASSWORDS.hash(PASSWORD)
    assert login(client, "demo-alice@example.test").headers["location"] == "/espace"
    nonce = csrf(client.get("/espace"))
    for path in (
        "/admin",
        "/admin/courriers-locaux",
        "/organisateur",
        f"/organisateur/evenements/{EVENT_ID}",
    ):
        assert client.get(path).status_code == 403
    assert (
        client.post(
            "/admin/invitations",
            data={"csrf_token": nonce, "email": "test@example.test"},
        ).status_code
        == 403
    )
    assert not client.app.state.mailer.messages


def test_logout_requires_csrf_and_public_personalized_pages_are_not_cached(auth):
    client, _, _ = auth
    login(client)
    assert client.get("/").headers["cache-control"] == "no-store"
    assert client.post("/deconnexion", data={"csrf_token": "bad"}).status_code == 403
    assert client.get("/admin").status_code == 200


def test_upgrading_0001_preserves_existing_events_and_contacts(tmp_path, seeded_db):
    from alembic import command
    from sqlalchemy import MetaData, text

    from app.database import Database, migration_config
    from app.models import Base

    database = Database(f"sqlite:///{tmp_path / 'legacy.sqlite3'}")
    try:
        config = migration_config()
        with database.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0001")
        legacy = MetaData()
        legacy.reflect(database.engine)
        with database.engine.begin() as target, seeded_db.engine.connect() as source:
            for table in legacy.sorted_tables:
                if table.name == "alembic_version":
                    continue
                columns = [
                    c.name
                    for c in table.columns
                    if c.name in Base.metadata.tables[table.name].c
                ]
                rows = (
                    source.execute(
                        select(
                            *(Base.metadata.tables[table.name].c[c] for c in columns)
                        )
                    )
                    .mappings()
                    .all()
                )
                if rows:
                    target.execute(table.insert(), [dict(row) for row in rows])
        database.initialize()
        database.check_schema()
        with database.sessions() as session:
            assert session.get(User, "demo-alice").name == "Alice Martin"
            assert session.scalar(select(func.count()).select_from(Contact)) == 12
            assert session.execute(text("PRAGMA foreign_key_check")).all() == []
    finally:
        database.close()
