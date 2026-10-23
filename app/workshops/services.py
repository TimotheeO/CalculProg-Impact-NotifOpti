import hashlib
import json
import re
from uuid import UUID

from sqlalchemy import select

from app.events.services import (
    PARIS,
    EventError,
    authorized_event,
    check_revision,
    parse_local,
    record_change,
    resolve_local,
    revision,
    workshops_for,
)
from app.models import (
    Change,
    Dependency,
    Enrollment,
    InvitationWorkshop,
    Participation,
    User,
    Workshop,
)
from app.notification_groups import enqueue_changes, recalculate_pending
from app.operations import begin_operation, log_action
from app.workshops.planning import plan_change
from app.workshops.types import FIELDS, WorkshopData
from src.graph import EventGraph
from src.impact import compute_impacted_set


def validate_workshop(form):
    values = {field: form.get(field, "").strip() for field in FIELDS}
    values["description"] = (
        values["description"].replace("\r\n", "\n").replace("\r", "\n")
    )
    errors, dates = {}, {}
    for field, maximum in (("name", 160), ("location", 240)):
        if not 1 <= len(values[field]) <= maximum:
            errors[field] = f"Ce champ doit contenir entre 1 et {maximum} caractères."
    if len(values["description"]) > 4000:
        errors["description"] = "La description est limitée à 4 000 caractères."
    capacity = None
    if values["capacity"]:
        if (
            not re.fullmatch(r"[0-9]{1,6}", values["capacity"])
            or not 1 <= int(values["capacity"]) <= 100000
        ):
            errors["capacity"] = (
                "Choisissez une capacité entre 1 et 100 000, ou laissez vide."
            )
        else:
            capacity = int(values["capacity"])
    if values["status"] not in {"active", "cancelled"}:
        errors["status"] = "Choisissez Actif ou Annulé."
    for field in ("starts_at", "ends_at"):
        try:
            dates[field] = parse_local(values[field])
        except ValueError as error:
            errors[field] = str(error)
    if len(dates) == 2 and dates["ends_at"] <= dates["starts_at"]:
        errors["ends_at"] = "La fin doit être postérieure au début."
    if errors:
        raise EventError("Corrigez les champs indiqués.", errors=errors)
    return WorkshopData(**{**values, **dates, "capacity": capacity})


def active_enrollments(session, workshop):
    return list(
        session.scalars(
            select(User)
            .join(Enrollment, Enrollment.user_id == User.id)
            .join(
                Participation,
                (Participation.event_id == Enrollment.event_id)
                & (Participation.user_id == Enrollment.user_id),
            )
            .where(
                Enrollment.workshop_id == workshop.id,
                Enrollment.event_id == workshop.event_id,
                Enrollment.status == "active",
                Participation.status == "confirmed",
                User.is_active.is_(True),
            )
            .order_by(User.name)
        )
    )


def workshop_for(session, event_id, workshop_id, actor_id):
    event = authorized_event(session, event_id, actor_id)
    workshop = session.scalar(
        select(Workshop).where(
            Workshop.id == workshop_id, Workshop.event_id == event_id
        )
    )
    if workshop is None:
        raise EventError("Atelier introuvable dans cet événement.", 404)
    return event, workshop


def validate_program(session, event, workshop, data):
    if event.status not in {"draft", "published"}:
        raise EventError("L’événement est fermé et reste en lecture seule.", 409)
    if not event.starts_at <= data.starts_at < data.ends_at <= event.ends_at:
        raise EventError(
            "L’atelier doit être entièrement compris dans les dates de l’événement.",
            errors={
                "starts_at": "Vérifiez la période de l’événement.",
                "ends_at": "Vérifiez la période de l’événement.",
            },
        )
    count = len(active_enrollments(session, workshop)) if workshop else 0
    if data.capacity is not None and data.capacity < count:
        raise EventError(
            f"La capacité ne peut pas être inférieure aux {count} inscriptions déjà confirmées.",
            errors={"capacity": "Capacité inférieure au nombre d’inscrits."},
        )
    if (
        workshop
        and workshop.status == "cancelled"
        and data.status == "active"
        and session.scalar(
            select(Enrollment.user_id)
            .where(Enrollment.workshop_id == workshop.id)
            .limit(1)
        )
    ):
        raise EventError(
            "Cet atelier a été utilisé. Sa réactivation nécessite une nouvelle confirmation des participants, prévue au cycle 2.",
            409,
        )


def create_workshop(session, event_id, actor_id, creation_id, data, now):
    event = authorized_event(session, event_id, actor_id)
    try:
        workshop_id = str(UUID(creation_id))
    except (ValueError, TypeError, AttributeError) as error:
        raise EventError("Ouvrez un nouveau formulaire de création.", 400) from error
    existing = session.get(Workshop, workshop_id)
    if existing:
        if existing.event_id != event_id:
            raise EventError("Atelier introuvable.", 404)
        return existing
    validate_program(session, event, None, data)
    workshop = Workshop(
        id=workshop_id,
        event_id=event_id,
        created_at=now,
        **{field: getattr(data, field) for field in FIELDS},
    )
    session.add(workshop)
    session.flush()
    log_action(
        session,
        event_id,
        actor_id,
        "workshop_created",
        now,
        target_id=workshop.id,
        detail={"name": workshop.name},
    )
    return workshop


def workshop_revision(session, event, workshops=None):
    rows = workshops if workshops is not None else workshops_for(session, event.id)
    links = sorted(
        (edge.base_workshop_id, edge.dependent_workshop_id)
        for edge in session.scalars(
            select(Dependency).where(Dependency.event_id == event.id)
        )
    )
    return hashlib.sha256(
        json.dumps(
            {"program": revision(event, rows), "dependencies": links}, sort_keys=True
        ).encode()
    ).hexdigest()


def preview_workshop(session, event_id, workshop_id, actor_id, data, expected):
    event, workshop = workshop_for(session, event_id, workshop_id, actor_id)
    if expected != workshop_revision(session, event):
        raise EventError(
            "Le programme ou ses dépendances ont changé. Rechargez le formulaire et vérifiez le nouvel aperçu.",
            409,
        )
    validate_program(session, event, workshop, data)
    workshops = workshops_for(session, event_id)
    dependencies = list(
        session.scalars(select(Dependency).where(Dependency.event_id == event_id))
    )
    plan = plan_change(workshops, dependencies, workshop_id, data)
    by_id = {w.id: w for w in workshops}
    for planned in plan.changes:
        try:
            validate_program(session, event, by_id[planned.workshop_id], planned.after)
            if planned.automatic and {"starts_at", "ends_at"} & set(planned.fields):
                for value in (planned.after.starts_at, planned.after.ends_at):
                    resolve_local(value.astimezone(PARIS).replace(tzinfo=None))
        except (EventError, ValueError) as error:
            if not planned.automatic:
                raise
            raise EventError(
                f"Le changement déplacerait « {planned.after.name} » hors du programme autorisé, ou vers une heure locale ambiguë. Adaptez les dates de l’événement ou le créneau choisi.",
                422,
            ) from error
    return event, workshop, plan


def delete_workshop(
    session, event_id, workshop_id, actor_id, expected, confirmation, now
):
    event, workshop = workshop_for(session, event_id, workshop_id, actor_id)
    check_revision(event, workshops_for(session, event_id), expected)
    if event.status != "draft":
        raise EventError(
            "Seul un atelier inutilisé d’un brouillon peut être supprimé. Annulez un atelier publié pour conserver son historique.",
            409,
        )
    for model, condition in (
        (Enrollment, Enrollment.workshop_id == workshop_id),
        (InvitationWorkshop, InvitationWorkshop.workshop_id == workshop_id),
        (Change, Change.workshop_id == workshop_id),
        (
            Dependency,
            (Dependency.base_workshop_id == workshop_id)
            | (Dependency.dependent_workshop_id == workshop_id),
        ),
    ):
        if session.scalar(select(model).where(condition).limit(1)):
            raise EventError(
                "Cet atelier possède des inscriptions, invitations, changements ou dépendances. Conservez-le et annulez-le si nécessaire.",
                409,
            )
    if confirmation.strip() != workshop.name:
        raise EventError(
            "Recopiez le nom exact de l’atelier pour confirmer sa suppression."
        )
    log_action(
        session,
        event_id,
        actor_id,
        "workshop_deleted",
        now,
        target_id=workshop_id,
        detail={"name": workshop.name},
    )
    session.delete(workshop)


def update_workshop(
    session,
    event_id,
    workshop_id,
    actor_id,
    data,
    expected,
    now,
    *,
    operation_id=None,
    window=60,
):
    event, workshop = workshop_for(session, event_id, workshop_id, actor_id)
    operation, fresh = begin_operation(
        session,
        event_id,
        actor_id,
        "workshop_updated",
        {
            **{f: getattr(data, f) for f in FIELDS},
            "workshop_id": workshop_id,
            "revision": expected,
        },
        now,
        operation_id,
    )
    if not fresh:
        return workshop
    _, _, plan = preview_workshop(
        session, event_id, workshop_id, actor_id, data, expected
    )
    by_id = {w.id: w for w in workshops_for(session, event_id)}
    changes = []
    for planned in plan.changes:
        target = by_id[planned.workshop_id]
        if planned.automatic:
            log_action(
                session,
                event_id,
                actor_id,
                "workshop_cascade_applied",
                now,
                target_id=target.id,
                detail={
                    "source_id": workshop_id,
                    "source_name": data.name,
                    "reason": planned.reason,
                    "operation_id": operation.id,
                    "fields": list(planned.fields),
                },
            )
        for field in planned.fields:
            if event.status == "published":
                change = record_change(
                    session,
                    event,
                    actor_id,
                    field,
                    getattr(planned.before, field),
                    getattr(planned.after, field),
                    now,
                    workshop_id=target.id,
                )
                change.operation_id, change.notification_scope = (
                    operation.id,
                    "workshop",
                )
                changes.append(change)
            setattr(target, field, getattr(planned.after, field))
    session.flush()
    enqueue_changes(session, changes, now, window)
    return workshop


def dependency_graph(session, event_id):
    graph = EventGraph()
    for workshop in workshops_for(session, event_id):
        graph.add_workshop(workshop.id, workshop.name)
    for dependency in session.scalars(
        select(Dependency).where(Dependency.event_id == event_id)
    ):
        graph.add_dependency(
            dependency.base_workshop_id, dependency.dependent_workshop_id
        )
    return graph


def change_dependency(
    session, event_id, actor_id, base_id, dependent_id, remove, now, window
):
    event = authorized_event(session, event_id, actor_id)
    if event.status not in {"draft", "published"}:
        raise EventError("Cet événement est fermé.", 409)
    graph = dependency_graph(session, event_id)
    if base_id not in graph.workshops or dependent_id not in graph.workshops:
        raise EventError("Choisissez deux ateliers de cet événement.")
    if base_id == dependent_id:
        raise EventError("Un atelier ne peut pas dépendre de lui-même.")
    key = (event_id, base_id, dependent_id)
    dependency = session.get(Dependency, key)
    if remove:
        if dependency is None:
            return
        session.delete(dependency)
    else:
        if dependency:
            return
        if base_id in compute_impacted_set(graph, dependent_id).impacted_workshop_ids:
            raise EventError(
                "Cette dépendance créerait une boucle. Retirez un lien de la cascade avant de l’ajouter."
            )
        session.add(
            Dependency(
                event_id=event_id,
                base_workshop_id=base_id,
                dependent_workshop_id=dependent_id,
            )
        )
    log_action(
        session,
        event_id,
        actor_id,
        "dependency_removed" if remove else "dependency_added",
        now,
        detail={
            "base": graph.workshops[base_id].name,
            "dependent": graph.workshops[dependent_id].name,
        },
    )
    session.flush()
    recalculate_pending(session, now, window)
