"""Adaptation persistante des changements au BFS et aux fenêtres fixes par personne."""

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select

from app.impact import audience, workshop_change_audience
from app.models import (
    Change,
    Event,
    EventAction,
    Notification,
    NotificationChange,
    Workshop,
)

FIELD_LABELS = {
    "name": "nom",
    "description": "description",
    "location": "lieu",
    "starts_at": "début",
    "ends_at": "fin",
    "status": "état",
    "capacity": "capacité",
    "participation_mode": "participation",
}


def targets_for_change(session, change, *, cache=None):
    # Cache limité à un seul recalcul sous transaction : aucune cible périmée
    # ne survit à une modification d’inscription ou à la tentative suivante.
    key = (
        change.notification_scope,
        change.event_id,
        change.workshop_id,
        change.operation_id,
        change.field == "status" and change.new_value == "cancelled",
    )
    if cache is not None and key in cache:
        return cache[key]
    if change.notification_scope == "workshop":
        result = workshop_change_audience(
            session,
            change.event_id,
            change.workshop_id,
            {change.field: change.new_value},
        )
        if change.operation_id:
            action = session.scalar(
                select(EventAction).where(
                    EventAction.event_id == change.event_id,
                    EventAction.target_id == change.workshop_id,
                    EventAction.kind == "workshop_cascade_applied",
                    EventAction.detail["operation_id"].as_string()
                    == change.operation_id,
                )
            )
            if action:
                result.reasons = {
                    user_id: reason + " · " + action.detail["reason"]
                    for user_id, reason in result.reasons.items()
                }
    else:
        result = audience(session, change.event_id)
    if cache is not None:
        cache[key] = result
    return result


def attach_change(session, change, user_id, reason, now, window):
    done = session.scalar(
        select(Notification.id)
        .join(NotificationChange, NotificationChange.notification_id == Notification.id)
        .where(
            NotificationChange.change_id == change.id,
            Notification.user_id == user_id,
            Notification.status.not_in(("pending", "ready")),
        )
        .limit(1)
    )
    if done:
        return
    existing_link = session.execute(
        select(NotificationChange, Notification)
        .join(Notification, Notification.id == NotificationChange.notification_id)
        .where(
            NotificationChange.change_id == change.id,
            Notification.user_id == user_id,
            Notification.status.in_(("pending", "ready")),
        )
    ).first()
    if existing_link:
        existing_link[0].active = True
        return
    notification = session.scalar(
        select(Notification)
        .where(
            Notification.event_id == change.event_id,
            Notification.user_id == user_id,
            Notification.status == "pending",
            Notification.due_at > now,
        )
        .order_by(Notification.opened_at)
        .limit(1)
    )
    original_due = change.created_at + timedelta(seconds=window)
    if notification is not None:
        if original_due <= now and notification.opened_at > change.created_at:
            # Un ancien groupe en retard ne doit pas faire partir un nouveau groupe trop tôt.
            notification = None
        else:
            notification.opened_at = min(notification.opened_at, change.created_at)
            notification.due_at = min(notification.due_at, original_due)
    if notification is None and change.operation_id and original_due <= now:
        # Les champs d’une même confirmation doivent rester ensemble, même si
        # le participant rejoint la file à l’échéance ou si la fenêtre vaut zéro.
        same_operation = (
            select(NotificationChange.notification_id)
            .join(Change, Change.id == NotificationChange.change_id)
            .where(Change.operation_id == change.operation_id)
        )
        notification = session.scalar(
            select(Notification)
            .where(
                Notification.event_id == change.event_id,
                Notification.user_id == user_id,
                Notification.status.in_(("pending", "ready")),
                Notification.due_at == original_due,
                Notification.id.in_(same_operation),
            )
            .order_by(Notification.opened_at, Notification.id)
            .limit(1)
        )
    if notification is None:
        due = original_due
        notification = Notification(
            id=str(uuid4()),
            event_id=change.event_id,
            user_id=user_id,
            message="",
            urgency=2,
            status="pending" if due > now else "ready",
            opened_at=change.created_at,
            due_at=due,
            reason=reason,
            created_at=now,
        )
        session.add(notification)
        session.flush()
    session.add(
        NotificationChange(
            event_id=change.event_id,
            notification_id=notification.id,
            change_id=change.id,
            active=True,
        )
    )
    session.flush()


def enqueue_changes(session, changes, now, window):
    target_cache = {}
    for change in changes:
        if change.notification_scope == "none":
            continue
        recipients = targets_for_change(session, change, cache=target_cache)
        for user in recipients.users:
            attach_change(
                session, change, user.id, recipients.reasons[user.id], now, window
            )
    session.flush()


def recalculate_pending(session, now, window):
    target_cache = {}
    pending_ids = (
        select(NotificationChange.change_id)
        .join(Notification, Notification.id == NotificationChange.notification_id)
        .where(Notification.status.in_(("pending", "ready")))
    )
    changes = list(
        session.scalars(
            select(Change).where(
                Change.notification_scope != "none",
                or_(
                    Change.id.in_(pending_ids),
                    Change.created_at > now - timedelta(seconds=window),
                ),
            )
        )
    )
    for change in changes:
        recipients = targets_for_change(session, change, cache=target_cache)
        ids = {u.id for u in recipients.users}
        for link, notification in session.execute(
            select(NotificationChange, Notification)
            .join(Notification, Notification.id == NotificationChange.notification_id)
            .where(
                NotificationChange.change_id == change.id,
                Notification.status.in_(("pending", "ready")),
            )
        ):
            link.active = notification.user_id in ids
        for user in recipients.users:
            attach_change(
                session, change, user.id, recipients.reasons[user.id], now, window
            )
    session.flush()
    notifications = list(
        session.scalars(
            select(Notification).where(
                Notification.status.in_(("pending", "ready")),
                Notification.due_at.is_not(None),
            )
        )
    )
    for notification in notifications:
        body, urgency, reasons, naive = build_content(
            session, notification, target_cache=target_cache
        )
        (
            notification.message,
            notification.urgency,
            notification.reason,
            notification.naive_requests,
        ) = body, urgency, reasons, naive
        if notification.due_at <= now:
            notification.status = "ready" if body else "skipped"
    session.flush()


def display_value(field, value):
    if value is None:
        return "illimitée" if field == "capacity" else "—"
    if field in {"starts_at", "ends_at"}:
        from zoneinfo import ZoneInfo

        return (
            datetime.fromisoformat(value)
            .astimezone(ZoneInfo("Europe/Paris"))
            .strftime("%d/%m/%Y à %H h %M")
        )
    if field == "status":
        return {"cancelled": "annulé", "active": "actif", "published": "publié"}.get(
            value, str(value)
        )
    if field == "participation_mode":
        return "sur invitation" if value == "invitation" else "ouvert aux demandes"
    return str(value)


def build_content(session, notification, *, target_cache=None):
    rows = list(
        session.execute(
            select(NotificationChange, Change)
            .join(Change, Change.id == NotificationChange.change_id)
            .where(NotificationChange.notification_id == notification.id)
            .order_by(Change.sequence, Change.created_at, Change.id)
        )
    )
    naive = len({change.operation_id or change.id for _, change in rows})
    effective = {}
    reasons = set()
    for link, change in rows:
        if not link.active:
            continue
        key = (change.workshop_id, change.field)
        if key not in effective:
            effective[key] = [change.old_value, change.new_value, change]
        else:
            effective[key][1:] = [change.new_value, change]
    parts, urgency = [], 2
    event = session.get(Event, notification.event_id)
    event_cancelled = event.status == "cancelled"
    for (workshop_id, field), (old, new, change) in effective.items():
        if old == new:
            continue
        workshop = session.get(Workshop, workshop_id) if workshop_id else None
        cancelled = workshop.status == "cancelled" if workshop else event_cancelled
        if (event_cancelled or cancelled) and not (
            field == "status" and new == "cancelled"
        ):
            continue
        # Une information encore en file et remplacée par un changement plus récent est caduque.
        latest = session.scalar(
            select(Change)
            .where(
                Change.event_id == change.event_id,
                Change.workshop_id == workshop_id,
                Change.field == field,
                Change.notification_scope != "none",
            )
            .order_by(
                Change.sequence.desc(), Change.created_at.desc(), Change.id.desc()
            )
            .limit(1)
        )
        if latest and latest.id != change.id and latest.new_value != new:
            continue
        title = workshop.name if workshop else "Événement"
        parts.append(
            f"{title} — {FIELD_LABELS.get(field, field)} : {display_value(field, old)} → {display_value(field, new)}"
        )
        urgency = min(
            urgency,
            0
            if field == "status" and new == "cancelled"
            else 1
            if field in {"starts_at", "ends_at"}
            else 2,
        )
        recipients = targets_for_change(session, change, cache=target_cache)
        if notification.user_id in recipients.reasons:
            reasons.add(recipients.reasons[notification.user_id])
    return "\n".join(parts), urgency, " ; ".join(sorted(reasons)), naive
