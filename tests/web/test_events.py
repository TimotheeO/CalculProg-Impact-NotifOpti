import html
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text

from app.auth.security import PASSWORDS
from app.database import Database
from app.events.services import (
    PARIS,
    EventError,
    create_event,
    form_values,
    parse_local,
    publish_event,
    revision,
    update_event,
    validate_data,
    workshops_for,
)
from app.models import (
    AuthSession,
    Change,
    Dependency,
    Event,
    EventOrganizer,
    Invitation,
    Participation,
    ParticipationRequest,
    User,
    Workshop,
)
from app.seeds import EVENT_ID, OWNER_ID, SECOND_EVENT_ID
from app.web import create_app

PASSWORD = "Phrase fictive pour la recette des evenements 42!"
HASHED = PASSWORDS.hash(PASSWORD)
NOW = datetime(2026, 10, 22, 9, tzinfo=timezone.utc)
VALID = {
    "name": "Rencontre du quartier",
    "description": "Un moment à partager.",
    "location": "Maison des associations",
    "starts_at": "2026-10-29T13:00",
    "ends_at": "2026-10-29T18:00",
    "participation_mode": "open",
}


def hidden(response, name):
    match = re.search(r'name="' + name + r'" value="([^"]*)"', response.text)
    assert match, response.text
    return html.unescape(match[1])


def login(client, email="demo-thomas@example.test"):
    csrf = hidden(client.get("/connexion"), "csrf_token")
    response = client.post(
        "/connexion",
        data={"csrf_token": csrf, "email": email, "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


@pytest.fixture
def organizer(seeded_db, web_settings):
    with seeded_db.transaction() as session:
        for user_id in (OWNER_ID, "demo-lea", "demo-alice"):
            session.get(User, user_id).password_hash = HASHED
    with TestClient(create_app(web_settings, clock=lambda: NOW)) as client:
        login(client)
        yield client


def create(client, **overrides):
    page = client.get("/organisateur/evenements/nouveau")
    assert page.status_code == 200
    fields = {
        **VALID,
        "csrf_token": hidden(page, "csrf_token"),
        "creation_id": hidden(page, "creation_id"),
        **overrides,
    }
    response = client.post(
        "/organisateur/evenements/nouveau", data=fields, follow_redirects=False
    )
    return response, fields


def created_id(response):
    assert response.status_code == 303, response.text
    return response.headers["location"].rsplit("/", 1)[-1]


def edit_fields(client, event_id, **overrides):
    page = client.get(f"/organisateur/evenements/{event_id}/modifier")
    assert page.status_code == 200
    return {
        "csrf_token": hidden(page, "csrf_token"),
        "revision": hidden(page, "revision"),
        "action": "confirm",
        **overrides,
    }


def fields_for(database, event_id):
    with database.sessions() as session:
        return form_values(session.get(Event, event_id))


def publish(client, event_id):
    page = client.get(f"/organisateur/evenements/{event_id}")
    return client.post(
        f"/organisateur/evenements/{event_id}/publier",
        data={
            "csrf_token": hidden(page, "csrf_token"),
            "revision": hidden(page, "revision"),
        },
        follow_redirects=False,
    )


def add_workshops(
    database, event_id, *, start="2026-10-29T14:00", end="2026-10-29T15:00"
):
    with database.transaction() as session:
        for suffix in ("a", "b"):
            session.add(
                Workshop(
                    id=f"{event_id}-{suffix}",
                    event_id=event_id,
                    name=f"Atelier {suffix}",
                    location="Salle A",
                    starts_at=parse_local(start),
                    ends_at=parse_local(end),
                )
            )
        session.flush()
        session.add(
            Dependency(
                event_id=event_id,
                base_workshop_id=f"{event_id}-a",
                dependent_workshop_id=f"{event_id}-b",
            )
        )


def test_create_from_empty_database_and_reopen_without_seed(database, web_settings):
    with database.transaction() as session:
        session.add(
            User(
                id="owner",
                name="Organisateur",
                email="owner@example.test",
                password_hash=HASHED,
                role="organizer",
            )
        )
    with TestClient(create_app(web_settings, clock=lambda: NOW)) as client:
        login(client, "owner@example.test")
        event_id = created_id(create(client)[0])
    reopened = Database(database.url)
    try:
        with reopened.sessions() as session:
            event = session.get(Event, event_id)
            assert event.owner_id == "owner" and event.status == "draft"
            assert (
                event.name == VALID["name"]
                and event.description == VALID["description"]
            )
            assert event.starts_at == datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
        with TestClient(create_app(web_settings, clock=lambda: NOW)) as client:
            login(client, "owner@example.test")
            assert VALID["name"] in client.get("/organisateur").text
    finally:
        reopened.close()


def test_creation_assigns_owner_and_draft_on_server_and_duplicate_post_is_idempotent(
    organizer, seeded_db
):
    response, fields = create(
        organizer, owner_id="demo-lea", status="published", slug="forged"
    )
    event_id = created_id(response)
    repeated = organizer.post(
        "/organisateur/evenements/nouveau", data=fields, follow_redirects=False
    )
    assert repeated.headers["location"] == response.headers["location"]
    with seeded_db.sessions() as session:
        event = session.get(Event, event_id)
        assert (
            event.owner_id == OWNER_ID
            and event.status == "draft"
            and event.slug != "forged"
        )
        assert session.scalar(select(func.count()).select_from(Event)) == 3


def test_same_name_can_create_two_distinct_events(organizer, seeded_db):
    first, second = (created_id(create(organizer)[0]) for _ in range(2))
    assert first != second
    with seeded_db.sessions() as session:
        assert session.get(Event, first).slug != session.get(Event, second).slug


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", " "),
        ("name", "x" * 161),
        ("location", ""),
        ("location", "x" * 241),
        ("description", "x" * 4001),
        ("participation_mode", "public"),
        ("starts_at", "2026-02-30T12:00"),
        ("starts_at", "not-a-date"),
        ("starts_at", "2026-10-29T13:00Z"),
        ("starts_at", "2101-10-29T13:00"),
        ("ends_at", "2026-10-29T13:00"),
        ("ends_at", "2026-10-29T12:59"),
    ],
)
def test_invalid_creation_has_field_error_and_preserves_other_values(
    organizer, seeded_db, field, value
):
    response, _ = create(organizer, **{field: value})
    assert response.status_code == 422
    assert (
        'aria-invalid="true"' in response.text
        and f'id="{field}-error"' in response.text
    )
    assert (
        "Maison des associations" in response.text
        if field != "location"
        else VALID["name"] in response.text
    )
    with seeded_db.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Event)) == 2


@pytest.mark.parametrize(
    "value,fragment",
    [("2026-03-29T02:30", "n’existe pas"), ("2026-10-25T02:30", "apparaît deux fois")],
)
def test_dst_gap_and_ambiguous_local_times_are_rejected(organizer, value, fragment):
    response, _ = create(organizer, starts_at=value)
    assert response.status_code == 422 and fragment in response.text


def test_large_valid_unicode_description_is_accepted_but_oversized_body_is_not(
    organizer,
):
    assert create(organizer, description="🌱" * 4000)[0].status_code == 303
    response = organizer.post(
        "/organisateur/evenements/nouveau",
        content="name=" + "x" * 65537,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 413


@pytest.mark.parametrize("mode", ["open", "invitation"])
def test_draft_is_private_and_only_published_open_event_is_public(
    organizer, seeded_db, mode
):
    event_id = created_id(create(organizer, participation_mode=mode)[0])
    with seeded_db.sessions() as session:
        slug = session.get(Event, event_id).slug
    assert VALID["name"] not in organizer.get("/").text
    assert organizer.get(f"/events/{slug}").status_code == 404
    assert publish(organizer, event_id).status_code == 303
    assert organizer.get(f"/events/{slug}").status_code == (
        200 if mode == "open" else 404
    )
    assert (VALID["name"] in organizer.get("/").text) == (mode == "open")
    with seeded_db.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Participation)
                .where(Participation.event_id == event_id)
            )
            == 0
        )


def test_duplicate_publication_keeps_one_history_record(organizer, seeded_db):
    event_id = created_id(create(organizer)[0])
    page = organizer.get(f"/organisateur/evenements/{event_id}")
    fields = {
        "csrf_token": hidden(page, "csrf_token"),
        "revision": hidden(page, "revision"),
    }
    for _ in range(2):
        assert (
            organizer.post(
                f"/organisateur/evenements/{event_id}/publier",
                data=fields,
                follow_redirects=False,
            ).status_code
            == 303
        )
    with seeded_db.sessions() as session:
        change = session.scalars(
            select(Change).where(Change.event_id == event_id)
        ).one()
        assert (
            change.field == "status"
            and change.old_value == "draft"
            and change.new_value == "published"
        )
        assert change.actor_id == OWNER_ID


def test_preview_does_not_write_then_confirmation_keeps_slug_and_records_published_change(
    organizer, seeded_db
):
    event_id = created_id(create(organizer)[0])
    publish(organizer, event_id)
    fields = edit_fields(
        organizer, event_id, **{**VALID, "name": "Nouveau nom", "action": "preview"}
    )
    response = organizer.post(
        f"/organisateur/evenements/{event_id}/modifier", data=fields
    )
    assert response.status_code == 200 and "Après confirmation" in response.text
    with seeded_db.sessions() as session:
        assert session.get(Event, event_id).name == VALID["name"]
        original_slug = session.get(Event, event_id).slug
    fields["action"] = "confirm"
    assert (
        organizer.post(
            f"/organisateur/evenements/{event_id}/modifier",
            data=fields,
            follow_redirects=False,
        ).status_code
        == 303
    )
    with seeded_db.sessions() as session:
        event = session.get(Event, event_id)
        assert event.name == "Nouveau nom" and event.slug == original_slug
        change = session.scalars(
            select(Change).where(Change.event_id == event_id, Change.field == "name")
        ).one()
        assert (
            change.old_value == VALID["name"]
            and change.new_value == "Nouveau nom"
            and change.created_at == NOW
        )
    current = edit_fields(organizer, event_id, **fields_for(seeded_db, event_id))
    organizer.post(f"/organisateur/evenements/{event_id}/modifier", data=current)
    with seeded_db.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Change)
                .where(Change.event_id == event_id)
            )
            == 2
        )


def test_stale_edit_and_stale_publication_do_not_overwrite_changes(
    organizer, seeded_db
):
    event_id = created_id(create(organizer)[0])
    fields = edit_fields(
        organizer, event_id, **{**VALID, "name": "Première correction"}
    )
    assert (
        organizer.post(
            f"/organisateur/evenements/{event_id}/modifier",
            data=fields,
            follow_redirects=False,
        ).status_code
        == 303
    )
    fields["name"] = "Ancien onglet"
    assert (
        organizer.post(
            f"/organisateur/evenements/{event_id}/modifier", data=fields
        ).status_code
        == 409
    )
    assert (
        organizer.post(
            f"/organisateur/evenements/{event_id}/publier",
            data={key: fields[key] for key in ("csrf_token", "revision")},
        ).status_code
        == 409
    )
    with seeded_db.sessions() as session:
        event = session.get(Event, event_id)
        assert event.name == "Première correction" and event.status == "draft"


def test_program_change_invalidates_open_event_form(organizer, seeded_db):
    event_id = created_id(create(organizer)[0])
    fields = edit_fields(organizer, event_id, **{**VALID, "name": "Correction"})
    add_workshops(seeded_db, event_id)
    assert (
        organizer.post(
            f"/organisateur/evenements/{event_id}/modifier", data=fields
        ).status_code
        == 409
    )


def test_shift_preserves_paris_wall_time_across_dst_and_preview_is_read_only(
    organizer, seeded_db
):
    event_id = created_id(
        create(organizer, starts_at="2026-10-22T13:00", ends_at="2026-10-22T18:00")[0]
    )
    add_workshops(seeded_db, event_id, start="2026-10-22T14:00", end="2026-10-22T15:00")
    fields = edit_fields(organizer, event_id, **{**VALID, "action": "preview"})
    response = organizer.post(
        f"/organisateur/evenements/{event_id}/modifier", data=fields
    )
    assert response.status_code == 200 and "29/10/2026 à 14 h 00" in response.text
    with seeded_db.sessions() as session:
        assert session.get(Workshop, f"{event_id}-a").starts_at == datetime(
            2026, 10, 22, 12, tzinfo=timezone.utc
        )
    fields["action"] = "confirm"
    assert (
        organizer.post(
            f"/organisateur/evenements/{event_id}/modifier",
            data=fields,
            follow_redirects=False,
        ).status_code
        == 303
    )
    with seeded_db.sessions() as session:
        for workshop in workshops_for(session, event_id):
            assert workshop.starts_at == datetime(2026, 10, 29, 13, tzinfo=timezone.utc)
            assert workshop.starts_at.astimezone(PARIS).hour == 14


def test_invalid_program_boundaries_roll_back_event_and_every_workshop(
    organizer, seeded_db
):
    event_id = created_id(create(organizer)[0])
    add_workshops(seeded_db, event_id)
    fields = edit_fields(
        organizer,
        event_id,
        **{**VALID, "ends_at": "2026-10-29T14:30", "name": "Ne pas conserver"},
    )
    response = organizer.post(
        f"/organisateur/evenements/{event_id}/modifier", data=fields
    )
    assert response.status_code == 422 and "sortirait" in response.text
    with seeded_db.sessions() as session:
        assert session.get(Event, event_id).name == VALID["name"]
        assert session.get(Workshop, f"{event_id}-a").ends_at == parse_local(
            "2026-10-29T15:00"
        )


@pytest.mark.parametrize("status", ["archived", "cancelled"])
def test_closed_event_is_read_only(organizer, seeded_db, status):
    event_id = created_id(create(organizer)[0])
    fields = edit_fields(organizer, event_id, **VALID)
    with seeded_db.transaction() as session:
        session.get(Event, event_id).status = status
    assert (
        organizer.get(f"/organisateur/evenements/{event_id}/modifier").status_code
        == 409
    )
    assert (
        organizer.post(
            f"/organisateur/evenements/{event_id}/modifier", data=fields
        ).status_code
        == 409
    )
    assert (
        "Modifier les informations"
        not in organizer.get(f"/organisateur/evenements/{event_id}").text
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("location", "Nouveau lieu"),
        ("starts_at", "2026-10-22T13:01"),
        ("ends_at", "2026-10-22T21:00"),
    ],
)
def test_important_changes_with_confirmed_participants_create_targeted_groups(
    organizer, seeded_db, field, value
):
    original = fields_for(seeded_db, EVENT_ID)
    fields = edit_fields(
        organizer, EVENT_ID, **{**original, "name": "Ne pas conserver", field: value}
    )
    response = organizer.post(
        f"/organisateur/evenements/{EVENT_ID}/modifier",
        data=fields,
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    from app.models import Notification

    with seeded_db.sessions() as session:
        assert getattr(session.get(Event, EVENT_ID), field) != original[field]
        assert (
            session.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.event_id == EVENT_ID, Notification.due_at.is_not(None)
                )
            )
            == 8
        )


def test_new_confirmed_participant_after_preview_is_recalculated(organizer, seeded_db):
    event_id = created_id(create(organizer)[0])
    fields = edit_fields(
        organizer,
        event_id,
        **{**VALID, "location": "Nouveau lieu", "action": "preview"},
    )
    assert (
        organizer.post(
            f"/organisateur/evenements/{event_id}/modifier",
            data=fields,
            follow_redirects=False,
        ).status_code
        == 200
    )
    with seeded_db.transaction() as session:
        session.add(Participation(event_id=event_id, user_id="demo-alice"))
    fields["action"] = "confirm"
    assert (
        organizer.post(
            f"/organisateur/evenements/{event_id}/modifier",
            data=fields,
            follow_redirects=False,
        ).status_code
        == 303
    )


def test_pending_requests_do_not_become_participants_on_publication_or_mode_change(
    organizer, seeded_db
):
    event_id = created_id(create(organizer)[0])
    with seeded_db.transaction() as session:
        session.add(ParticipationRequest(event_id=event_id, user_id="demo-chloe"))
    publish(organizer, event_id)
    fields = edit_fields(
        organizer, event_id, **{**VALID, "participation_mode": "invitation"}
    )
    assert (
        organizer.post(
            f"/organisateur/evenements/{event_id}/modifier",
            data=fields,
            follow_redirects=False,
        ).status_code
        == 303
    )
    with seeded_db.sessions() as session:
        assert (
            session.get(ParticipationRequest, (event_id, "demo-chloe")).status
            == "pending"
        )
        assert session.get(Participation, (event_id, "demo-chloe")) is None
    assert (
        "Participants confirmés · 0"
        in organizer.get(f"/organisateur/evenements/{event_id}").text
    )


def test_delete_needs_explicit_confirmation_and_removes_only_unused_configuration(
    organizer, seeded_db
):
    event_id = created_id(create(organizer)[0])
    add_workshops(seeded_db, event_id)
    with seeded_db.transaction() as session:
        session.add(EventOrganizer(event_id=event_id, user_id="demo-lea"))
    page = organizer.get(f"/organisateur/evenements/{event_id}/supprimer")
    fields = {
        "csrf_token": hidden(page, "csrf_token"),
        "revision": hidden(page, "revision"),
        "confirmation": "wrong",
    }
    assert (
        organizer.post(
            f"/organisateur/evenements/{event_id}/supprimer", data=fields
        ).status_code
        == 422
    )
    with seeded_db.sessions() as session:
        assert session.get(Event, event_id) is not None
    fields["confirmation"] = VALID["name"]
    assert (
        organizer.post(
            f"/organisateur/evenements/{event_id}/supprimer",
            data=fields,
            follow_redirects=False,
        ).status_code
        == 303
    )
    with seeded_db.sessions() as session:
        assert session.get(Event, event_id) is None
        assert workshops_for(session, event_id) == []
        assert session.get(Event, EVENT_ID) is not None
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []


@pytest.mark.parametrize(
    "activity",
    ["participation", "request", "invitation", "change", "past_participation"],
)
def test_any_existing_activity_blocks_draft_deletion(organizer, seeded_db, activity):
    event_id = created_id(create(organizer)[0])
    with seeded_db.transaction() as session:
        if activity in {"participation", "past_participation"}:
            session.add(
                Participation(
                    event_id=event_id,
                    user_id="demo-alice",
                    status="withdrawn"
                    if activity == "past_participation"
                    else "confirmed",
                )
            )
        elif activity == "request":
            session.add(ParticipationRequest(event_id=event_id, user_id="demo-chloe"))
        elif activity == "invitation":
            session.add(
                Invitation(
                    id=str(uuid4()),
                    event_id=event_id,
                    email="invite@example.test",
                    inviter_id=OWNER_ID,
                    token_digest=str(uuid4()),
                    expires_at=parse_local("2026-12-01T14:00"),
                    created_at=NOW,
                )
            )
        else:
            session.add(
                Change(
                    id=str(uuid4()),
                    event_id=event_id,
                    actor_id=OWNER_ID,
                    field="name",
                    old_value="A",
                    new_value="B",
                )
            )
    with seeded_db.sessions() as session:
        expected = revision(session.get(Event, event_id), [])
    fields = {
        "csrf_token": hidden(organizer.get("/organisateur"), "csrf_token"),
        "revision": expected,
        "confirmation": VALID["name"],
    }
    assert (
        organizer.post(
            f"/organisateur/evenements/{event_id}/supprimer", data=fields
        ).status_code
        == 409
    )
    with seeded_db.sessions() as session:
        assert session.get(Event, event_id) is not None


def test_published_event_cannot_be_deleted_even_without_participants(organizer):
    event_id = created_id(create(organizer)[0])
    publish(organizer, event_id)
    page = organizer.get(f"/organisateur/evenements/{event_id}/modifier")
    response = organizer.post(
        f"/organisateur/evenements/{event_id}/supprimer",
        data={
            "csrf_token": hidden(page, "csrf_token"),
            "revision": hidden(page, "revision"),
            "confirmation": VALID["name"],
        },
    )
    assert response.status_code == 409


def test_coorganizer_can_edit_and_publish_but_cannot_delete_owners_draft(
    organizer, seeded_db
):
    event_id = created_id(create(organizer)[0])
    with seeded_db.transaction() as session:
        session.add(EventOrganizer(event_id=event_id, user_id="demo-lea"))
    organizer.cookies.clear()
    login(organizer, "demo-lea@example.test")
    fields = edit_fields(organizer, event_id, **{**VALID, "name": "Préparé ensemble"})
    assert (
        organizer.post(
            f"/organisateur/evenements/{event_id}/modifier",
            data=fields,
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert (
        organizer.get(f"/organisateur/evenements/{event_id}/supprimer").status_code
        == 403
    )
    assert (
        organizer.post(
            f"/organisateur/evenements/{event_id}/supprimer",
            data={**fields, "confirmation": "Préparé ensemble"},
        ).status_code
        == 403
    )
    assert publish(organizer, event_id).status_code == 303


@pytest.mark.parametrize("suffix", ["", "/modifier", "/supprimer"])
def test_other_event_is_not_disclosed(organizer, suffix):
    response = organizer.get(f"/organisateur/evenements/{SECOND_EVENT_ID}{suffix}")
    assert (
        response.status_code == 404 and "La Fabrique du vendredi" not in response.text
    )


@pytest.mark.parametrize("action", ["modifier", "publier", "supprimer"])
def test_cross_event_posts_and_csrf_are_rejected(organizer, action):
    csrf = hidden(organizer.get("/organisateur"), "csrf_token")
    assert (
        organizer.post(
            f"/organisateur/evenements/{SECOND_EVENT_ID}/{action}",
            data={"csrf_token": csrf},
        ).status_code
        == 404
    )
    assert (
        organizer.post(
            f"/organisateur/evenements/{EVENT_ID}/{action}",
            data={"csrf_token": "wrong"},
        ).status_code
        == 403
    )


def test_anonymous_and_participant_cannot_create_or_manage_events(organizer, seeded_db):
    organizer.cookies.clear()
    assert (
        organizer.get(
            "/organisateur/evenements/nouveau", follow_redirects=False
        ).status_code
        == 303
    )
    assert (
        organizer.post(
            "/organisateur/evenements/nouveau", data=VALID, follow_redirects=False
        ).status_code
        == 303
    )
    login(organizer, "demo-alice@example.test")
    assert organizer.get("/organisateur/evenements/nouveau").status_code == 403
    assert (
        organizer.post("/organisateur/evenements/nouveau", data=VALID).status_code
        == 403
    )
    assert organizer.get(f"/organisateur/evenements/{EVENT_ID}").status_code == 403


def test_private_participants_and_requests_are_visible_only_in_authorized_details(
    organizer,
):
    page = organizer.get(f"/organisateur/evenements/{EVENT_ID}")
    assert "Participants confirmés · 8" in page.text
    assert "Alice Martin" in page.text and "demo-bruno@example.test" in page.text
    assert "Alice Martin" not in organizer.get("/").text


def test_untrusted_html_is_escaped_in_form_preview_and_public_page(organizer):
    name = '<script>alert("xss")</script>'
    event_id = created_id(
        create(organizer, name=name, description='<img src=x onerror="alert(1)">')[0]
    )
    page = organizer.get(f"/organisateur/evenements/{event_id}")
    assert name not in page.text and "&lt;script&gt;" in page.text
    assert "<img src=x" not in page.text
    fields = edit_fields(
        organizer, event_id, **{**VALID, "name": name, "action": "preview"}
    )
    preview = organizer.post(
        f"/organisateur/evenements/{event_id}/modifier", data=fields
    )
    assert name not in preview.text and "&lt;script&gt;" in preview.text


def test_concurrent_creation_of_same_submission_produces_one_event(seeded_db):
    creation_id = str(uuid4())
    data = validate_data(VALID)

    def attempt(_):
        with seeded_db.transaction(immediate=True) as session:
            return create_event(session, OWNER_ID, creation_id, data, NOW).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(attempt, range(2))) == [creation_id, creation_id]
    with seeded_db.sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Event).where(Event.id == creation_id)
            )
            == 1
        )


def test_failure_after_publication_rolls_back_state_and_history(seeded_db):
    with seeded_db.transaction(immediate=True) as session:
        event = create_event(session, OWNER_ID, str(uuid4()), validate_data(VALID), NOW)
        event_id = event.id
        expected = revision(event, [])
    with pytest.raises(RuntimeError), seeded_db.transaction(immediate=True) as session:
        publish_event(session, event_id, OWNER_ID, expected, NOW)
        raise RuntimeError("abandon volontaire")
    with seeded_db.sessions() as session:
        assert session.get(Event, event_id).status == "draft"
        assert (
            session.scalar(
                select(func.count())
                .select_from(Change)
                .where(Change.event_id == event_id)
            )
            == 0
        )


def test_concurrent_edits_only_accept_one_version(seeded_db):
    with seeded_db.transaction(immediate=True) as session:
        event = create_event(session, OWNER_ID, str(uuid4()), validate_data(VALID), NOW)
        event_id, expected = event.id, revision(event, [])

    def attempt(number):
        try:
            with seeded_db.transaction(immediate=True) as session:
                update_event(
                    session,
                    event_id,
                    OWNER_ID,
                    validate_data({**VALID, "name": f"Version {number}"}),
                    expected,
                    NOW,
                )
            return "saved"
        except EventError as error:
            assert error.status == 409
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["saved", "stale"]


def test_returning_from_preview_preserves_entered_values_without_saving(
    organizer, seeded_db
):
    event_id = created_id(create(organizer)[0])
    fields = edit_fields(
        organizer,
        event_id,
        **{
            **VALID,
            "name": "Saisie à conserver",
            "description": "Ligne 1\nLigne 2",
            "action": "revise",
        },
    )
    page = organizer.post(f"/organisateur/evenements/{event_id}/modifier", data=fields)
    assert (
        page.status_code == 200
        and "Saisie à conserver" in page.text
        and "Ligne 1\nLigne 2" in page.text
    )
    assert hidden(page, "revision") == fields["revision"]
    with seeded_db.sessions() as session:
        assert session.get(Event, event_id).name == VALID["name"]


def test_creation_csrf_and_foreign_origin_are_rejected(organizer):
    _, fields = create(organizer)
    assert (
        organizer.post(
            "/organisateur/evenements/nouveau", data={**fields, "csrf_token": "wrong"}
        ).status_code
        == 403
    )
    assert (
        organizer.post(
            "/organisateur/evenements/nouveau",
            data=fields,
            headers={"Origin": "https://foreign.example"},
        ).status_code
        == 403
    )


def test_program_shift_into_ambiguous_hour_is_rejected_atomically(organizer, seeded_db):
    event_id = created_id(
        create(organizer, starts_at="2026-10-18T00:00", ends_at="2026-10-18T05:00")[0]
    )
    add_workshops(seeded_db, event_id, start="2026-10-18T02:30", end="2026-10-18T03:30")
    fields = edit_fields(
        organizer,
        event_id,
        **{**VALID, "starts_at": "2026-10-25T00:00", "ends_at": "2026-10-25T05:00"},
    )
    response = organizer.post(
        f"/organisateur/evenements/{event_id}/modifier", data=fields
    )
    assert response.status_code == 422 and "invalide ou ambigu" in response.text
    with seeded_db.sessions() as session:
        assert session.get(Event, event_id).starts_at == parse_local("2026-10-18T00:00")


def test_published_event_without_participants_uses_audited_change_service(
    organizer, seeded_db
):
    event_id = created_id(create(organizer)[0])
    add_workshops(seeded_db, event_id)
    publish(organizer, event_id)
    fields = edit_fields(
        organizer,
        event_id,
        **{
            **VALID,
            "starts_at": "2026-11-05T13:00",
            "ends_at": "2026-11-05T18:00",
            "location": "Nouveau lieu",
        },
    )
    assert (
        organizer.post(
            f"/organisateur/evenements/{event_id}/modifier",
            data=fields,
            follow_redirects=False,
        ).status_code
        == 303
    )
    with seeded_db.sessions() as session:
        changes = list(
            session.scalars(select(Change).where(Change.event_id == event_id))
        )
        assert sum(c.workshop_id is not None for c in changes) == 4
        assert any(
            c.field == "location"
            and c.old_value == VALID["location"]
            and c.new_value == "Nouveau lieu"
            for c in changes
        )
        assert session.get(Workshop, f"{event_id}-a").starts_at == parse_local(
            "2026-11-05T14:00"
        )
    assert organizer.app.state.mailer.messages == ()


def test_stale_delete_cannot_remove_a_modified_draft(organizer, seeded_db):
    event_id = created_id(create(organizer)[0])
    page = organizer.get(f"/organisateur/evenements/{event_id}/supprimer")
    deletion = {
        "csrf_token": hidden(page, "csrf_token"),
        "revision": hidden(page, "revision"),
        "confirmation": VALID["name"],
    }
    fields = edit_fields(
        organizer, event_id, **{**VALID, "description": "Une modification récente"}
    )
    organizer.post(f"/organisateur/evenements/{event_id}/modifier", data=fields)
    assert (
        organizer.post(
            f"/organisateur/evenements/{event_id}/supprimer", data=deletion
        ).status_code
        == 409
    )
    with seeded_db.sessions() as session:
        assert session.get(Event, event_id).description == "Une modification récente"


@pytest.mark.parametrize("revocation", ["logout", "disabled", "role_changed"])
def test_access_revoked_after_initial_form_check_cannot_create_event(
    organizer, seeded_db, monkeypatch, revocation
):
    from app.events import routes

    original = routes.form_context

    def revoke_after_check(request, identity, form):
        original(request, identity, form)
        with seeded_db.transaction(immediate=True) as session:
            if revocation == "logout":
                session.execute(
                    delete(AuthSession).where(AuthSession.user_id == OWNER_ID)
                )
            elif revocation == "disabled":
                session.get(User, OWNER_ID).is_active = False
            else:
                session.get(User, OWNER_ID).role = "participant"

    monkeypatch.setattr(routes, "form_context", revoke_after_check)
    response, _ = create(organizer)
    assert response.status_code == 403
    with seeded_db.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Event)) == 2
