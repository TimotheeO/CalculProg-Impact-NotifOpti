"""Journal autorisé et compteurs calculés sur les fenêtres fermées."""

import hashlib
import json
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from app.auth.http import (
    Identity,
    checked_participant,
    checked_user,
    current_identity,
    read_selection,
    render,
    required_participant,
    required_user,
)
from app.deliveries import retry_delivery
from app.events.services import EventError, authorized_event
from app.models import (
    Change,
    Event,
    EventAction,
    MailAttempt,
    MailDelivery,
    Notification,
    User,
)

MAIL_STATES = {
    "pending": "En file",
    "sending": "Tentative en cours",
    "simulated": "Simulé en mémoire",
    "accepted": "Accepté par le transport",
    "failed": "Échec confirmé",
    "uncertain": "Résultat incertain — vérifier le transport",
}
NOTIFICATION_STATES = {
    "pending": "Regroupement en cours",
    "ready": "Prêt, attend le débit",
    "sending": "Tentative en cours",
    "sent": "Tentative terminée",
    "failed": "Échec d’envoi",
    "uncertain": "Résultat incertain",
    "skipped": "Aucun changement pertinent à envoyer",
}


def snapshot(session, event_id=None, user_id=None):
    query = select(Notification)
    deliveries = select(MailDelivery)
    if event_id:
        query = query.where(Notification.event_id == event_id)
        deliveries = deliveries.where(MailDelivery.event_id == event_id)
    if user_id:
        query = query.where(Notification.user_id == user_id)
        deliveries = deliveries.where(MailDelivery.user_id == user_id)
    rows = list(
        session.scalars(query.order_by(Notification.created_at.desc(), Notification.id))
    )
    mail = list(
        session.scalars(
            deliveries.order_by(MailDelivery.created_at.desc(), MailDelivery.id)
        )
    )
    # Les fenêtres en cours ne constituent aucune économie réalisée.
    closed = [n for n in rows if n.due_at is not None and n.status != "pending"]
    naive = sum(n.naive_requests for n in closed)
    final = sum(bool(n.message) and n.status != "skipped" for n in closed)
    return (
        rows,
        mail,
        {
            "naive": naive,
            "final": final,
            "saved": max(0, naive - final),
            "closed": len(closed),
        },
    )


def fingerprint(rows, mail, changes=(), actions=()):
    payload = (
        [
            (
                r.id,
                r.status,
                r.message,
                r.reason,
                r.read_at.isoformat() if r.read_at else None,
            )
            for r in rows
        ],
        [(m.id, m.status, m.error_code) for m in mail],
        [c.id for c in changes],
        [a.id for a in actions],
    )
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def router():
    result = APIRouter()

    def event_data(request, event_id, identity):
        with request.app.state.database.sessions() as session:
            event = authorized_event(session, event_id, identity.user.id)
            rows, mail, stats = snapshot(session, event_id=event_id)
            changes = list(
                session.scalars(
                    select(Change)
                    .where(Change.event_id == event_id)
                    .order_by(
                        Change.sequence.desc(), Change.created_at.desc(), Change.id
                    )
                )
            )
            actions = list(
                session.scalars(
                    select(EventAction)
                    .where(EventAction.event_id == event_id)
                    .order_by(EventAction.created_at.desc(), EventAction.id)
                )
            )
            users = {u.id: u.name for u in session.scalars(select(User))}
        return event, rows, mail, stats, changes, actions, users

    @result.get("/organisateur/evenements/{event_id}/journal", name="event_journal")
    def journal(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        event, rows, mail, stats, changes, actions, users = event_data(
            request, event_id, identity
        )
        with request.app.state.database.sessions() as session:
            attempts = list(
                session.scalars(
                    select(MailAttempt)
                    .join(MailDelivery, MailDelivery.id == MailAttempt.delivery_id)
                    .where(MailDelivery.event_id == event_id)
                    .order_by(MailAttempt.started_at.desc())
                )
            )
        return render(
            request,
            "journal.html",
            identity,
            event=event,
            notifications=rows,
            deliveries=mail,
            stats=stats,
            changes=changes,
            actions=actions,
            users=users,
            mail_states=MAIL_STATES,
            notification_states=NOTIFICATION_STATES,
            live_url=f"/organisateur/evenements/{event_id}/journal/etat",
            live_revision=fingerprint(rows, mail, changes, actions),
            worker_error=request.app.state.scheduler.last_error,
            settings=request.app.state.settings,
            attempts=attempts,
            retry_operations={m.id: str(uuid4()) for m in mail},
        )

    @result.get("/organisateur/evenements/{event_id}/journal/etat")
    def journal_state(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        _, rows, mail, _, changes, actions, _ = event_data(request, event_id, identity)
        return JSONResponse({"revision": fingerprint(rows, mail, changes, actions)})

    @result.post("/organisateur/evenements/{event_id}/envois/{delivery_id}/reessayer")
    def retry(
        request: Request,
        event_id: str,
        delivery_id: str,
        form: Annotated[dict, Depends(read_selection)],
    ):
        with request.app.state.database.transaction(immediate=True) as session:
            user = checked_user(request, session, form, "organizer")
            retry_delivery(
                session,
                event_id,
                delivery_id,
                user.id,
                form.get("operation_id"),
                request.app.state.clock(),
                reviewed=form.get("reviewed") == "yes",
                note=form.get("note", ""),
            )
        from app.mailer import MemoryMailer

        if isinstance(request.app.state.mailer, MemoryMailer):
            request.app.state.scheduler.tick()
        return RedirectResponse(
            f"/organisateur/evenements/{event_id}/journal", status_code=303
        )

    @result.get("/espace/notifications", name="notification_box")
    def box(request: Request, identity: Annotated[Identity, Depends(current_identity)]):
        if response := required_participant(identity):
            return response
        with request.app.state.database.sessions() as session:
            rows, mail, _ = snapshot(session, user_id=identity.user.id)
            archived_event_ids = set(
                session.scalars(
                    select(Event.id).where(
                        Event.status == "archived",
                        Event.id.in_([n.event_id for n in rows]),
                    )
                )
            )
        return render(
            request,
            "participation/notifications.html",
            identity,
            notifications=rows,
            deliveries=mail,
            archived_event_ids=archived_event_ids,
            mail_states=MAIL_STATES,
            notification_states=NOTIFICATION_STATES,
            live_url="/espace/notifications/etat",
            live_revision=fingerprint(rows, mail),
        )

    @result.get("/espace/notifications/etat")
    def box_state(
        request: Request, identity: Annotated[Identity, Depends(current_identity)]
    ):
        if response := required_participant(identity):
            return response
        with request.app.state.database.sessions() as session:
            rows, mail, _ = snapshot(session, user_id=identity.user.id)
        return JSONResponse({"revision": fingerprint(rows, mail)})

    @result.post("/espace/notifications/{notification_id}/lire")
    def read(
        request: Request,
        notification_id: str,
        form: Annotated[dict, Depends(read_selection)],
    ):
        with request.app.state.database.transaction(immediate=True) as session:
            user = checked_participant(request, session, form)
            row = session.get(Notification, notification_id)
            if not row or row.user_id != user.id:
                raise EventError("Notification introuvable.", 404)
            if session.get(Event, row.event_id).status == "archived":
                raise EventError(
                    "Les notifications d’une archive restent en lecture seule.", 409
                )
            if row.status not in {"pending", "skipped"}:
                row.read_at = request.app.state.clock()
        return RedirectResponse("/espace/notifications", status_code=303)

    return result
