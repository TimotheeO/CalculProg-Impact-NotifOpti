from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Change,
    Dependency,
    Enrollment,
    Event,
    EventOrganizer,
    Participation,
    User,
    Workshop,
)
from src.graph import EventGraph


class DomainError(Exception):
    """Erreur métier attendue, présentable sans détail SQL."""


class NotFound(DomainError):
    pass


class Forbidden(DomainError):
    pass


class InvalidChange(DomainError):
    pass


def load_graph(session: Session, event_id: str) -> EventGraph:
    """Reconstruit un événement depuis les seuls liens actifs ; aucun envoi."""
    if session.get(Event, event_id) is None:
        raise NotFound("Événement introuvable")

    graph = EventGraph()
    users = session.scalars(
        select(User)
        .join(Participation, Participation.user_id == User.id)
        .where(
            Participation.event_id == event_id,
            Participation.status == "confirmed",
            User.is_active.is_(True),
        )
        .order_by(User.id)
    )
    for user in users:
        graph.add_participant(user.id, user.name)
    for workshop in session.scalars(
        select(Workshop)
        .where(Workshop.event_id == event_id, Workshop.status == "active")
        .order_by(Workshop.id)
    ):
        graph.add_workshop(workshop.id, workshop.name)
    for enrollment in session.scalars(
        select(Enrollment).where(
            Enrollment.event_id == event_id, Enrollment.status == "active"
        )
    ):
        if (
            enrollment.user_id in graph.participants
            and enrollment.workshop_id in graph.workshops
        ):
            graph.enroll(enrollment.user_id, enrollment.workshop_id)
    for dependency in session.scalars(
        select(Dependency).where(Dependency.event_id == event_id)
    ):
        if (
            dependency.base_workshop_id in graph.workshops
            and dependency.dependent_workshop_id in graph.workshops
        ):
            graph.add_dependency(
                dependency.base_workshop_id, dependency.dependent_workshop_id
            )
    return graph


def change_workshop_location(
    session: Session, event_id: str, workshop_id: str, actor_id: str, new_location: str
) -> Change | None:
    """Première écriture métier atomique, réservée à la CLI locale en C1-02.

    L’appelant ouvre la transaction. Les formulaires et notifications arrivent
    dans C1-05/C1-08/C1-09 ; cette fonction ne prétend pas les implémenter.
    """
    event = session.get(Event, event_id)
    if event is None:
        raise NotFound("Événement introuvable")
    actor = session.get(User, actor_id)
    if (
        actor is None
        or not actor.is_active
        or actor.role not in {"organizer", "super_admin"}
        or (
            event.owner_id != actor_id
            and session.get(EventOrganizer, (event_id, actor_id)) is None
        )
    ):
        raise Forbidden("Cet organisateur n’est pas autorisé à modifier cet événement")
    if event.status in {"archived", "cancelled"}:
        raise InvalidChange("Un événement annulé ou archivé ne peut pas être modifié")
    workshop = session.get(Workshop, workshop_id)
    if workshop is None or workshop.event_id != event_id:
        raise NotFound("Atelier introuvable dans cet événement")
    if workshop.status != "active":
        raise InvalidChange("Cet atelier est annulé")
    new_location = new_location.strip()
    if not new_location or len(new_location) > 240:
        raise InvalidChange("Le lieu doit contenir entre 1 et 240 caractères")
    if workshop.location == new_location:
        return None
    change = Change(
        id=str(uuid4()),
        event_id=event_id,
        workshop_id=workshop_id,
        actor_id=actor_id,
        field="location",
        old_value=workshop.location,
        new_value=new_location,
    )
    workshop.location = new_location
    session.add(change)
    session.flush()
    return change
