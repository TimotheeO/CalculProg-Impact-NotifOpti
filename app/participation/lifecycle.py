"""Retraits explicites et reconfirmation ; aucune réinscription automatique."""

from sqlalchemy import select

from app.auth.security import ensure_participation_allowed
from app.events.services import EventError, authorized_event
from app.models import (
    Enrollment,
    Event,
    Participation,
    ParticipationRequest,
    User,
    Workshop,
)
from app.notification_groups import recalculate_pending
from app.operations import begin_operation, log_action
from app.participation.services import replace_enrollments, validate_enrollments


def withdraw(
    session,
    event_id,
    user_id,
    actor_id,
    now,
    *,
    workshop_id=None,
    organizer=False,
    operation_id=None,
    window=60,
):
    event = (
        authorized_event(session, event_id, actor_id)
        if organizer
        else session.get(Event, event_id)
    )
    if not organizer and actor_id != user_id:
        raise EventError("Participation introuvable.", 404)
    if event is None:
        raise EventError("Événement introuvable.", 404)
    if event.status != "published":
        raise EventError("Cet événement est fermé ou archivé.", 409)
    person = session.get(User, user_id)
    ensure_participation_allowed(person)
    participation = session.get(Participation, (event_id, user_id))
    if participation is None:
        raise EventError("Participation introuvable.", 404)
    _, fresh = begin_operation(
        session,
        event_id,
        actor_id,
        "participant_removed" if organizer else "participant_withdrawn",
        {"user": user_id, "workshop": workshop_id},
        now,
        operation_id,
    )
    if not fresh:
        return
    desired = "removed" if organizer else "cancelled"
    if workshop_id:
        enrollment = session.get(Enrollment, (event_id, user_id, workshop_id))
        if enrollment is None:
            raise EventError("Inscription introuvable.", 404)
        if enrollment.status in {"active", "pending_confirmation"}:
            enrollment.status = desired
    else:
        participation.status = "removed" if organizer else "withdrawn"
        for enrollment in session.scalars(
            select(Enrollment).where(
                Enrollment.event_id == event_id,
                Enrollment.user_id == user_id,
                Enrollment.status.in_(("active", "pending_confirmation")),
            )
        ):
            enrollment.status = desired
        request = session.get(ParticipationRequest, (event_id, user_id))
        if request and request.status == "pending":
            request.status = "withdrawn"
    log_action(
        session,
        event_id,
        actor_id,
        "participant_removed" if organizer else "participant_withdrawn",
        now,
        target_id=user_id,
        detail={"workshop_id": workshop_id},
    )
    session.flush()
    recalculate_pending(session, now, window)


def confirm_participation(session, event_id, user_id, chosen, now, window):
    event = session.get(Event, event_id)
    participation = session.get(Participation, (event_id, user_id))
    if (
        not event
        or event.status != "published"
        or not participation
        or participation.status != "pending_confirmation"
    ):
        raise EventError("Aucune participation à confirmer pour cet événement.", 409)
    ensure_participation_allowed(session.get(User, user_id))
    selected = validate_enrollments(session, event, user_id, chosen)
    participation.status = "confirmed"
    session.flush()
    for enrollment in session.scalars(
        select(Enrollment).where(
            Enrollment.event_id == event_id,
            Enrollment.user_id == user_id,
            Enrollment.status == "pending_confirmation",
        )
    ):
        enrollment.status = "cancelled"
    replace_enrollments(session, event, user_id, selected, now)
    log_action(session, event_id, user_id, "participation_reconfirmed", now)
    session.flush()
    recalculate_pending(session, now, window)


def personal_planning(session, user_id):
    return list(
        session.execute(
            select(Workshop, Event)
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
            .order_by(Workshop.starts_at, Workshop.id)
        )
    )
