"""Ciblage web : même BFS que la CLI, explications et contrôles des conflits."""

from dataclasses import dataclass

from sqlalchemy import select

from app.models import Dependency, Enrollment, Event, Participation, User, Workshop
from src.graph import EventGraph
from src.impact import compute_impacted_set


@dataclass
class Audience:
    users: list
    reasons: dict
    spared: list
    workshops: list
    propagated: bool = False


def workshop_change_audience(session, event_id, workshop_id, changes):
    return audience(
        session,
        event_id,
        workshop_id,
        cancellation=changes.get("status") == "cancelled",
        reconfirmation=changes.get("status") == "active",
        propagate=False,
    )


def workshop_plan_audience(session, event_id, plan, field=None):
    """Union des inscrits aux ateliers effectivement modifiés, champ par champ."""
    all_users = audience(session, event_id).users
    reasons, impacted_workshops = {}, []
    propagated = False
    by_id = {
        w.id: w
        for w in session.scalars(select(Workshop).where(Workshop.event_id == event_id))
    }
    for planned in plan.changes:
        selected = {
            key: getattr(planned.after, key)
            for key in planned.fields
            if field is None or key == field
        }
        if not selected:
            continue
        impacted_workshops.append(by_id[planned.workshop_id])
        propagated |= planned.automatic
        direct = workshop_change_audience(
            session, event_id, planned.workshop_id, selected
        )
        for user in direct.users:
            reason = direct.reasons[user.id]
            if planned.automatic:
                reason += " · " + planned.reason
            reasons.setdefault(user.id, []).append(reason)
    return Audience(
        [u for u in all_users if u.id in reasons],
        {key: " ; ".join(dict.fromkeys(values)) for key, values in reasons.items()},
        [u for u in all_users if u.id not in reasons],
        impacted_workshops,
        propagated,
    )


def audience(
    session,
    event_id,
    workshop_id=None,
    *,
    cancellation=False,
    propagate=True,
    reconfirmation=False,
):
    users = list(
        session.scalars(
            select(User)
            .join(Participation, Participation.user_id == User.id)
            .where(
                Participation.event_id == event_id,
                Participation.status.in_(
                    ("confirmed", "pending_confirmation")
                    if reconfirmation
                    else ("confirmed",)
                ),
                User.is_active.is_(True),
                User.role != "super_admin",
            )
            .order_by(User.name, User.id)
        )
    )
    if workshop_id is None:
        return Audience(
            users, {u.id: "Changement global de l’événement" for u in users}, [], []
        )
    if not propagate:
        workshop = session.get(Workshop, workshop_id)
        if (
            workshop is None
            or workshop.event_id != event_id
            or (workshop.status != "active" and not cancellation)
        ):
            return Audience([], {}, users, [])
        enrolled = set(
            session.scalars(
                select(Enrollment.user_id).where(
                    Enrollment.event_id == event_id,
                    Enrollment.workshop_id == workshop_id,
                    Enrollment.status.in_(
                        ("active", "pending_confirmation")
                        if reconfirmation
                        else ("active",)
                    ),
                )
            )
        )
        return Audience(
            [user for user in users if user.id in enrolled],
            {
                user.id: f"Inscription directe à « {workshop.name} »"
                for user in users
                if user.id in enrolled
            },
            [user for user in users if user.id not in enrolled],
            [workshop],
        )
    graph = EventGraph()
    for user in users:
        graph.add_participant(user.id, user.name)
    workshops = list(
        session.scalars(select(Workshop).where(Workshop.event_id == event_id))
    )
    for workshop in workshops:
        if workshop.status == "active" or (cancellation and workshop.id == workshop_id):
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
    if propagate:
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
    if workshop_id not in graph.workshops:
        return Audience([], {}, users, [])
    result = compute_impacted_set(graph, workshop_id)
    direct = {
        e.user_id
        for e in session.scalars(
            select(Enrollment).where(
                Enrollment.event_id == event_id,
                Enrollment.workshop_id == workshop_id,
                Enrollment.status == "active",
            )
        )
    }
    source = graph.workshops[workshop_id].name
    reasons = {
        u.id: f"Inscription directe à « {source} »"
        if u.id in direct
        else f"Cascade depuis « {source} »"
        for u in users
        if u.id in result.impacted_participant_ids
    }
    return Audience(
        [u for u in users if u.id in reasons],
        reasons,
        [u for u in users if u.id not in reasons],
        [w for w in workshops if w.id in result.impacted_workshop_ids],
        propagated=propagate,
    )


def schedule_conflicts(session, event_id, planned):
    proposed = {workshop.id: (start, end) for workshop, start, end in planned}
    if not proposed:
        return []
    rows = list(
        session.execute(
            select(Enrollment, Workshop, User)
            .join(Workshop, Workshop.id == Enrollment.workshop_id)
            .join(
                Participation,
                (Participation.event_id == Enrollment.event_id)
                & (Participation.user_id == Enrollment.user_id),
            )
            .join(Event, Event.id == Enrollment.event_id)
            .join(User, User.id == Enrollment.user_id)
            .where(
                Enrollment.status == "active",
                Participation.status == "confirmed",
                Workshop.status == "active",
                Event.status == "published",
                User.is_active.is_(True),
            )
        )
    )
    conflicts = set()
    for enrollment, workshop, user in rows:
        if workshop.id not in proposed:
            continue
        start, end = proposed[workshop.id]
        for other_enrollment, other, _ in rows:
            if other_enrollment.user_id != user.id or other.id == workshop.id:
                continue
            other_start, other_end = proposed.get(
                other.id, (other.starts_at, other.ends_at)
            )
            if start < other_end and other_start < end:
                # Ne pas révéler le nom d’un événement tiers privé à cet organisateur.
                conflicts.add(
                    f"{user.name} : « {workshop.name} » chevaucherait un autre atelier déjà réservé. Les inscriptions seront conservées."
                )
    return sorted(conflicts)


def personal_conflicts(session, user_id):
    rows = list(
        session.scalars(
            select(Workshop)
            .join(Enrollment, Enrollment.workshop_id == Workshop.id)
            .join(Event, Event.id == Workshop.event_id)
            .join(
                Participation,
                (Participation.event_id == Enrollment.event_id)
                & (Participation.user_id == Enrollment.user_id),
            )
            .where(
                Enrollment.user_id == user_id,
                Enrollment.status == "active",
                Participation.status == "confirmed",
                Event.status == "published",
                Workshop.status == "active",
            )
            .order_by(Workshop.starts_at)
        )
    )
    return [
        f"Conflit horaire : « {left.name} » et « {right.name} » se chevauchent. Vos inscriptions sont conservées ; vérifiez votre planning."
        for index, left in enumerate(rows)
        for right in rows[index + 1 :]
        if left.starts_at < right.ends_at and right.starts_at < left.ends_at
    ]
