import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, or_, select

from app.models import (
    Change,
    Dependency,
    Enrollment,
    Event,
    EventAction,
    EventOperation,
    EventOrganizer,
    Invitation,
    Notification,
    Participation,
    ParticipationRequest,
    User,
    Workshop,
)
from app.services import DomainError

PARIS = ZoneInfo("Europe/Paris")
FIELDS = (
    "name",
    "description",
    "location",
    "starts_at",
    "ends_at",
    "participation_mode",
)


class EventError(DomainError):
    def __init__(self, message, status=422, *, errors=None):
        super().__init__(message)
        self.status = status
        self.errors = errors or {}


@dataclass(frozen=True)
class EventData:
    name: str
    description: str
    location: str
    starts_at: datetime
    ends_at: datetime
    participation_mode: str


def resolve_local(naive):
    """Un horaire Paris doit désigner un seul instant, y compris aux changements d’heure."""
    candidates = {
        utc
        for fold in (0, 1)
        if (utc := naive.replace(tzinfo=PARIS, fold=fold).astimezone(timezone.utc))
        .astimezone(PARIS)
        .replace(tzinfo=None)
        == naive
    }
    if not candidates:
        raise ValueError(
            "Cet horaire n’existe pas lors du passage à l’heure d’été. Choisissez un autre horaire."
        )
    if len(candidates) != 1:
        raise ValueError(
            "Cet horaire apparaît deux fois lors du passage à l’heure d’hiver. Choisissez un horaire non ambigu."
        )
    return candidates.pop()


def parse_local(value):
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}", value):
        raise ValueError("Renseignez une date et une heure valides.")
    try:
        naive = datetime.strptime(value, "%Y-%m-%dT%H:%M")  # noqa: DTZ007 — saisie civile résolue ensuite par fold et aller-retour UTC
    except ValueError as error:
        raise ValueError("Renseignez une date et une heure valides.") from error
    if not 1900 <= naive.year <= 2100:
        raise ValueError("Choisissez une année comprise entre 1900 et 2100.")
    return resolve_local(naive)


def validate_data(form):
    values = {field: form.get(field, "").strip() for field in FIELDS}
    values["description"] = (
        values["description"].replace("\r\n", "\n").replace("\r", "\n")
    )
    errors, dates = {}, {}
    for field, maximum, label in (("name", 160, "nom"), ("location", 240, "lieu")):
        if not 1 <= len(values[field]) <= maximum:
            errors[field] = f"Le {label} doit contenir entre 1 et {maximum} caractères."
    if len(values["description"]) > 4000:
        errors["description"] = "La description est limitée à 4 000 caractères."
    if values["participation_mode"] not in {"invitation", "open"}:
        errors["participation_mode"] = "Choisissez un mode de participation proposé."
    for field in ("starts_at", "ends_at"):
        try:
            dates[field] = parse_local(values[field])
        except ValueError as error:
            errors[field] = str(error)
    if len(dates) == 2 and dates["ends_at"] <= dates["starts_at"]:
        errors["ends_at"] = "La fin doit être postérieure au début de l’événement."
    if errors:
        raise EventError(
            "Corrigez les champs indiqués ; aucune donnée n’a été enregistrée.",
            errors=errors,
        )
    return EventData(**{**values, **dates})


def form_values(event):
    return {
        field: getattr(event, field).astimezone(PARIS).strftime("%Y-%m-%dT%H:%M")
        if field in {"starts_at", "ends_at"}
        else getattr(event, field)
        for field in FIELDS
    }


def organizer_actor(session, actor_id):
    actor = session.get(User, actor_id) if actor_id else None
    if actor is None or not actor.is_active or actor.role != "organizer":
        raise EventError("Cette action est réservée aux organisateurs actifs.", 403)
    return actor


def authorized_events(actor_id):
    return or_(
        Event.owner_id == actor_id,
        Event.id.in_(
            select(EventOrganizer.event_id).where(EventOrganizer.user_id == actor_id)
        ),
    )


def authorized_event(session, event_id, actor_id):
    organizer_actor(session, actor_id)
    event = session.scalar(
        select(Event).where(Event.id == event_id, authorized_events(actor_id))
    )
    if event is None:
        raise EventError("Événement introuvable.", 404)
    return event


def workshops_for(session, event_id):
    return list(
        session.scalars(
            select(Workshop)
            .where(Workshop.event_id == event_id)
            .order_by(Workshop.starts_at, Workshop.id)
        )
    )


def revision(event, workshops):
    """Empreinte de l’état relu sous verrou, sans colonne ni secret supplémentaire."""
    snapshot = {
        field: getattr(event, field)
        for field in (*FIELDS, "id", "owner_id", "slug", "status")
    }
    snapshot["workshops"] = [
        (
            w.id,
            w.name,
            w.description,
            w.location,
            w.starts_at,
            w.ends_at,
            w.status,
            w.capacity,
        )
        for w in sorted(workshops, key=lambda w: w.id)
    ]
    return hashlib.sha256(
        json.dumps(
            snapshot, default=lambda value: value.isoformat(), sort_keys=True
        ).encode()
    ).hexdigest()


def check_revision(event, workshops, expected):
    if revision(event, workshops) != expected:
        raise EventError(
            "L’événement ou son programme a changé depuis l’ouverture du formulaire. Rechargez la page pour vérifier la dernière version avant de recommencer.",
            409,
        )


def create_event(session, actor_id, creation_id, data, now):
    organizer_actor(session, actor_id)
    try:
        if len(creation_id) != 36:
            raise ValueError
        event_id = str(UUID(creation_id))
    except (ValueError, AttributeError) as error:
        raise EventError(
            "Le formulaire de création a expiré. Ouvrez un nouveau formulaire.", 400
        ) from error
    existing = session.get(Event, event_id)
    if existing:
        if existing.owner_id != actor_id:
            raise EventError("Événement introuvable.", 404)
        return (
            existing  # Double clic : retourner le brouillon existant sans le réécrire.
        )
    event = Event(
        id=event_id,
        slug=f"evenement-{event_id}",
        owner_id=actor_id,
        status="draft",
        created_at=now,
        **{field: getattr(data, field) for field in FIELDS},
    )
    session.add(event)
    session.flush()
    return event


def record_change(session, event, actor_id, field, old, new, now, *, workshop_id=None):
    # Un déplacement doit écrire début ET fin ensemble avant toute validation SQL.
    # La recherche de séquence ne doit pas provoquer un flush à mi-déplacement.
    with session.no_autoflush:
        stored = session.scalar(select(func.max(Change.sequence))) or 0
    pending = [row.sequence or 0 for row in session.new if isinstance(row, Change)]
    sequence = max([stored, *pending]) + 1
    change = Change(
        id=str(uuid4()),
        event_id=event.id,
        workshop_id=workshop_id,
        actor_id=actor_id,
        field=field,
        old_value=old.isoformat() if isinstance(old, datetime) else old,
        new_value=new.isoformat() if isinstance(new, datetime) else new,
        created_at=now,
        sequence=sequence,
    )
    session.add(change)
    return change


def planned_workshops(event, workshops, data):
    delta = data.starts_at.astimezone(PARIS).replace(
        tzinfo=None
    ) - event.starts_at.astimezone(PARIS).replace(tzinfo=None)
    planned = []
    for workshop in workshops:
        try:
            start, end = (
                resolve_local(value.astimezone(PARIS).replace(tzinfo=None) + delta)
                if delta
                else value
                for value in (workshop.starts_at, workshop.ends_at)
            )
        except (ValueError, OverflowError) as error:
            raise EventError(
                f"Le report rend l’horaire de « {workshop.name} » invalide ou ambigu. Choisissez un autre créneau."
            ) from error
        if not data.starts_at <= start < end <= data.ends_at:
            raise EventError(
                f"L’atelier « {workshop.name} » sortirait des dates de l’événement. Ajustez la période proposée."
            )
        planned.append((workshop, start, end))
    return planned


def preview_update(session, event_id, actor_id, data, expected):
    event = authorized_event(session, event_id, actor_id)
    workshops = workshops_for(session, event.id)
    check_revision(event, workshops, expected)
    if event.status not in {"draft", "published"}:
        raise EventError(
            "Cet événement est annulé ou archivé et ne peut pas être modifié.", 409
        )
    changed = [
        field for field in FIELDS if getattr(event, field) != getattr(data, field)
    ]
    planned = planned_workshops(event, workshops, data)
    return event, changed, planned


def update_event(
    session, event_id, actor_id, data, expected, now, *, operation_id=None, window=60
):
    from app.notification_groups import enqueue_changes
    from app.operations import begin_operation

    event = authorized_event(session, event_id, actor_id)
    operation, fresh = begin_operation(
        session,
        event_id,
        actor_id,
        "event_updated",
        {**{f: getattr(data, f) for f in FIELDS}, "revision": expected},
        now,
        operation_id,
    )
    if not fresh:
        return event
    event, changed, planned = preview_update(
        session, event_id, actor_id, data, expected
    )
    changes = []
    for field in changed:
        old, new = getattr(event, field), getattr(data, field)
        if event.status == "published":
            change = record_change(session, event, actor_id, field, old, new, now)
            change.operation_id, change.notification_scope = operation.id, "event"
            changes.append(change)
        setattr(event, field, new)
    for workshop, start, end in planned:
        for field, value in (("starts_at", start), ("ends_at", end)):
            if getattr(workshop, field) != value:
                if event.status == "published":
                    change = record_change(
                        session,
                        event,
                        actor_id,
                        field,
                        getattr(workshop, field),
                        value,
                        now,
                        workshop_id=workshop.id,
                    )
                    change.operation_id, change.notification_scope = (
                        operation.id,
                        "workshop",
                    )
                    changes.append(change)
                setattr(workshop, field, value)
    session.flush()
    enqueue_changes(session, changes, now, window)
    return event


def publish_event(session, event_id, actor_id, expected, now):
    event = authorized_event(session, event_id, actor_id)
    workshops = workshops_for(session, event.id)
    # Une répétition du même POST ne crée aucun deuxième changement.
    if (
        event.status == "published"
        and revision_with_draft(event, workshops) == expected
    ):
        return event
    check_revision(event, workshops, expected)
    if event.status != "draft":
        raise EventError("Seul un brouillon peut être publié.", 409)
    # Les données historiques sont aussi contrôlées avant leur première publication.
    data = validate_data(form_values(event))
    data = replace(data, starts_at=event.starts_at, ends_at=event.ends_at)
    planned_workshops(event, workshops, data)
    event.status = "published"
    record_change(session, event, actor_id, "status", "draft", "published", now)
    session.flush()
    return event


def revision_with_draft(event, workshops):
    # Pas de modification ORM : la publication idempotente compare un état synthétique.
    previous = SimpleNamespace(
        **{
            field: getattr(event, field)
            for field in (*FIELDS, "id", "owner_id", "slug")
        },
        status="draft",
    )
    return revision(previous, workshops)


def deletion_blockers(session, event):
    if event.status != "draft":
        return ["Seul un brouillon sans activité peut être supprimé."]
    blockers = []
    for model, label in (
        (Invitation, "invitations"),
        (ParticipationRequest, "demandes de participation"),
        (Participation, "participations"),
        (Enrollment, "inscriptions"),
        (Notification, "notifications"),
        (Change, "historique de changements"),
    ):
        if (
            session.scalar(
                select(model.event_id).where(model.event_id == event.id).limit(1)
            )
            is not None
        ):
            blockers.append(
                f"Cet événement possède des {label}."
                if model != Change
                else "Cet événement possède un historique de changements."
            )
    return blockers


def delete_draft(session, event_id, actor_id, expected, confirmation):
    event = authorized_event(session, event_id, actor_id)
    if event.owner_id != actor_id:
        raise EventError(
            "Seul le responsable principal peut supprimer ce brouillon.", 403
        )
    check_revision(event, workshops_for(session, event.id), expected)
    blockers = deletion_blockers(session, event)
    if blockers:
        raise EventError(
            " ".join(blockers)
            + " Ses participations et son historique doivent être conservés.",
            409,
        )
    if confirmation.strip() != event.name:
        raise EventError(
            "Recopiez exactement le nom de l’événement pour confirmer la suppression.",
            errors={"confirmation": "Le nom ne correspond pas."},
        )
    # Le programme et les autorisations sont de la configuration ; aucune activité n’est effacée.
    for model in (Dependency, EventOrganizer, Workshop, EventOperation, EventAction):
        session.execute(delete(model).where(model.event_id == event.id))
    session.delete(event)
    session.flush()


def cancel_event(
    session, event_id, actor_id, expected, now, *, operation_id=None, window=60
):
    from app.notification_groups import enqueue_changes
    from app.operations import begin_operation

    event = authorized_event(session, event_id, actor_id)
    operation, fresh = begin_operation(
        session,
        event_id,
        actor_id,
        "event_cancelled",
        {"revision": expected},
        now,
        operation_id,
    )
    if not fresh:
        return event
    check_revision(event, workshops_for(session, event.id), expected)
    if event.status != "published":
        raise EventError("Seul un événement publié peut être annulé ici.", 409)
    change = record_change(
        session, event, actor_id, "status", event.status, "cancelled", now
    )
    change.operation_id, change.notification_scope = operation.id, "event"
    event.status = "cancelled"
    session.flush()
    enqueue_changes(session, [change], now, window)
    return event
