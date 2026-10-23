"""La base prête doit permettre la présentation sans écraser le travail existant."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.auth.security import digest, password_matches
from app.config import Settings
from app.database import Database
from app.demo import ADMIN_ID, DEMO_PASSWORD, prepare
from app.events.services import PARIS
from app.impact import audience
from app.models import (
    Contact,
    Event,
    Invitation,
    MailDelivery,
    Notification,
    OrganizerInvitation,
    Participation,
    ParticipationRequest,
    User,
    Workshop,
)
from app.seeds import EVENT_ID, SECOND_EVENT_ID
from app.web import create_app
from tests.web.test_events import hidden

NOW = datetime(2026, 10, 22, 10, tzinfo=timezone.utc)


@pytest.fixture
def ready(tmp_path):
    directory, created = prepare(tmp_path / "ready", now=NOW)
    assert created
    database = Database(f"sqlite:///{directory / 'impactflow.sqlite3'}")
    yield directory, database
    database.close()


def test_ready_accounts_roles_dates_and_unique_bfs(ready):
    directory, database = ready
    with database.sessions() as session:
        users = list(session.scalars(select(User)))
        assert len(users) == 13
        assert {u.role for u in users} == {"participant", "organizer", "super_admin"}
        assert all(
            u.is_active and password_matches(u.password_hash, DEMO_PASSWORD)
            for u in users
        )
        assert len({u.password_hash for u in users}) == 13
        assert all(u.email.endswith("@example.test") for u in users)
        assert session.get(User, ADMIN_ID).role == "super_admin"
        event = session.get(Event, EVENT_ID)
        assert (
            event.starts_at.astimezone(PARIS).isoformat() == "2026-10-29T14:00:00+01:00"
        )
        assert event.ends_at.astimezone(PARIS).hour == 18
        assert session.get(Workshop, "w1").starts_at == event.starts_at
        assert len(audience(session, EVENT_ID, "w1").users) == 4
        assert len(audience(session, EVENT_ID, "w1").spared) == 4
        assert session.get(Event, "demo-brouillon").status == "draft"
        assert session.get(Event, SECOND_EVENT_ID).participation_mode == "open"
        assert (
            session.get(ParticipationRequest, (SECOND_EVENT_ID, "demo-chloe")).status
            == "pending"
        )
        assert session.scalar(select(func.count()).select_from(Notification)) == 0
        assert session.scalar(select(func.count()).select_from(MailDelivery)) == 0
        assert session.scalar(select(func.count()).select_from(Contact)) == 16
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
    assert directory.stat().st_mode & 0o077 == 0
    assert (directory / "impactflow.sqlite3").stat().st_mode & 0o077 == 0


def test_ready_invitations_are_real_unique_expiring_links_without_fake_mail(ready):
    directory, database = ready
    report = json.loads((directory / "preparation.json").read_text())
    assert len(report["invitations"]) == 4
    with database.sessions() as session:
        for link in report["invitations"]:
            token = link["url"].split("invitation=")[1]
            model = (
                OrganizerInvitation
                if "/activation-organisateur#" in link["url"]
                else Invitation
            )
            row = session.scalar(
                select(model).where(model.token_digest == digest(token))
            )
            assert row.status == "pending" and row.expires_at == NOW + timedelta(
                hours=48
            )
            assert token not in row.token_digest
            assert token in (directory / "invitations.html").read_text()
        assert (
            session.scalar(select(User).where(User.email == "camille@example.test"))
            is None
        )
        assert (
            session.scalar(select(User).where(User.email == "julie@example.test"))
            is None
        )


def test_preparation_replay_preserves_changes_and_database_bytes(ready):
    directory, database = ready
    with database.transaction() as session:
        session.get(Workshop, "w1").location = "Valeur changée par la recette"
    before = hashlib.sha256((directory / "impactflow.sqlite3").read_bytes()).hexdigest()
    assert prepare(directory, now=NOW + timedelta(days=10)) == (directory, False)
    assert (
        hashlib.sha256((directory / "impactflow.sqlite3").read_bytes()).hexdigest()
        == before
    )
    with database.sessions() as session:
        assert session.get(Workshop, "w1").location == "Valeur changée par la recette"


def test_existing_unknown_directory_is_never_overwritten(tmp_path):
    directory = tmp_path / "existing"
    directory.mkdir()
    file = directory / "impactflow.sqlite3"
    file.write_bytes(b"base-a-conserver")
    with pytest.raises(ValueError, match="aucune donnée écrasée"):
        prepare(directory, now=NOW)
    assert file.read_bytes() == b"base-a-conserver"


def test_failed_preparation_does_not_publish_partial_database(tmp_path, monkeypatch):
    import app.demo

    def broken(*args, **kwargs):
        raise RuntimeError("interruption")

    monkeypatch.setattr(app.demo, "_write_access", broken)
    directory = tmp_path / "unfinished"
    with pytest.raises(RuntimeError, match="interruption"):
        prepare(directory, now=NOW)
    assert not directory.exists()
    assert not list(tmp_path.glob(".impactflow-demo-*"))


@pytest.mark.parametrize(
    "email,path",
    [
        ("admin.demo@example.test", "/admin"),
        ("demo-thomas@example.test", "/organisateur"),
        ("demo-lea@example.test", "/organisateur"),
        ("demo-alice@example.test", "/espace"),
    ],
)
def test_ready_accounts_can_login(ready, email, path):
    directory, _ = ready
    settings = Settings(
        database_url=f"sqlite:///{directory / 'impactflow.sqlite3'}", environment="test"
    )
    with TestClient(create_app(settings, clock=lambda: NOW)) as client:
        nonce = hidden(client.get("/connexion"), "csrf_token")
        response = client.post(
            "/connexion",
            data={"csrf_token": nonce, "email": email, "password": DEMO_PASSWORD},
            follow_redirects=False,
        )
        assert response.status_code == 303 and response.headers["location"] == path
        assert client.get(path).status_code == 200


def test_ready_link_can_decline_without_account_or_accept_with_creation(ready):
    directory, database = ready
    report = json.loads((directory / "preparation.json").read_text())
    settings = Settings(
        database_url=f"sqlite:///{directory / 'impactflow.sqlite3'}", environment="test"
    )
    for email, action in [
        ("julie@example.test", "decline"),
        ("camille@example.test", "accept"),
    ]:
        token = next(
            link["url"].split("invitation=")[1]
            for link in report["invitations"]
            if link["email"] == email
        )
        with TestClient(create_app(settings, clock=lambda: NOW)) as client:
            import re

            page = client.get("/invitations")
            nonce = re.search(r'id="invitation-csrf" value="([^"]+)"', page.text)[1]
            assert (
                client.post(
                    "/invitations/preparer", data={"csrf_token": nonce, "token": token}
                ).status_code
                == 200
            )
            fields = {
                "csrf_token": hidden(client.get("/invitations"), "csrf_token"),
                "action": action,
                "name": "Camille Durand",
                "password": DEMO_PASSWORD,
                "password_confirmation": DEMO_PASSWORD,
                "workshop_ids": ["w1", "w2"],
            }
            response = client.post("/invitations", data=fields, follow_redirects=False)
            assert response.status_code == (303 if action == "accept" else 200)
    with database.sessions() as session:
        assert (
            session.scalar(select(User).where(User.email == "julie@example.test"))
            is None
        )
        user = session.scalar(select(User).where(User.email == "camille@example.test"))
        assert session.get(Participation, (EVENT_ID, user.id)).status == "confirmed"
