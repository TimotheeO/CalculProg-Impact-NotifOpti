"""Reconstruction des envois jamais tentés et relances explicitement autorisées."""

import secrets

from sqlalchemy import select

from app.auth.security import digest
from app.events.services import EventError, authorized_event
from app.mailer import MailMessage, compose_message
from app.models import (
    Event,
    Invitation,
    MailDelivery,
    OrganizerInvitation,
    PasswordReset,
    User,
)
from app.operations import begin_operation, log_action


def rebuild_message(session, settings, delivery, now):
    """Un jeton perdu en mémoire est renouvelé uniquement avant toute tentative."""
    invitation, path, kind = None, "", delivery.kind
    if delivery.invitation_id:
        invitation = session.get(OrganizerInvitation, delivery.invitation_id)
        path, kind = "activation-organisateur#invitation", "organizer_invitation"
    elif delivery.event_invitation_id:
        invitation = session.get(Invitation, delivery.event_invitation_id)
        path = "invitations#invitation"
        kind = (
            "event_invitation"
            if invitation.purpose == "invitation"
            else "request_verification"
        )
    elif delivery.password_reset_id:
        invitation = session.get(PasswordReset, delivery.password_reset_id)
        path, kind = "reinitialisation#reset", "password_reset"
    if invitation:
        token = secrets.token_urlsafe(32)
        invitation.token_digest = digest(token)
        event = session.get(Event, delivery.event_id) if delivery.event_id else None
        recipient = getattr(invitation, "email", None) or delivery.recipient
        if not recipient and delivery.user_id:
            recipient = session.get(User, delivery.user_id).email
        return compose_message(
            settings,
            delivery.id,
            recipient,
            kind,
            event_name=event.name if event else "",
            url=f"{settings.base_url}/{path}={token}",
            expires=invitation.expires_at.isoformat(),
        )
    context = delivery.context or {}
    if not context and delivery.kind == "request_response":
        from app.models import ParticipationRequest

        request = session.get(
            ParticipationRequest, (delivery.event_id, delivery.user_id)
        )
        event = session.get(Event, delivery.event_id)
        if request and request.status in {"accepted", "declined"}:
            return compose_message(
                settings,
                delivery.id,
                delivery.recipient,
                "request_response",
                event_name=event.name,
                content="Votre demande a été acceptée. Vous pouvez maintenant choisir vos ateliers."
                if request.status == "accepted"
                else "Votre demande de participation a été refusée par l’organisateur.",
            )
    if all(key in context for key in ("subject", "html", "text")):
        return MailMessage(
            delivery.id,
            delivery.recipient,
            context["subject"],
            context["html"],
            context["text"],
            f"{settings.base_url}/espace",
        )
    return None


def retry_delivery(
    session,
    event_id,
    delivery_id,
    actor_id,
    operation_id,
    now,
    *,
    reviewed=False,
    note="",
):
    event = authorized_event(session, event_id, actor_id)
    if event.status == "archived":
        raise EventError("Une archive reste en lecture seule.", 409)
    delivery = session.scalar(
        select(MailDelivery).where(
            MailDelivery.id == delivery_id, MailDelivery.event_id == event_id
        )
    )
    if delivery is None:
        raise EventError("Envoi introuvable.", 404)
    if not operation_id:
        raise EventError("Rechargez le formulaire de relance.", 400)
    _, fresh = begin_operation(
        session,
        event_id,
        actor_id,
        "mail_retry",
        {"delivery": delivery_id, "reviewed": reviewed, "note": note.strip()[:500]},
        now,
        operation_id,
    )
    if not fresh:
        return delivery
    if delivery.status == "uncertain":
        if not reviewed or len(note.strip()) < 10:
            raise EventError(
                "Vérifiez auprès du transport que l’envoi n’a pas été accepté, puis indiquez le résultat de cette vérification (10 caractères minimum).",
                409,
            )
    elif delivery.status != "failed":
        raise EventError(
            "Seul un échec confirmé peut être relancé. Une tentative en cours ou réussie ne peut pas être renvoyée.",
            409,
        )
    if delivery.error_code in {
        "no_longer_relevant",
        "invitation_replaced",
        "invitation_inactive",
    }:
        raise EventError(
            "Ce contenu n’est plus pertinent. Utilisez une nouvelle invitation ou un nouveau changement.",
            409,
        )
    if delivery.notification_id:
        from app.models import Notification

        notification = session.get(Notification, delivery.notification_id)
        notification.status = "ready"
    context = dict(delivery.context or {})
    context["retry_actor_id"] = actor_id
    delivery.context = context
    delivery.status, delivery.error_code, delivery.provider_id = "pending", None, None
    log_action(
        session,
        event_id,
        actor_id,
        "mail_retry_requested",
        now,
        target_id=delivery.id,
        detail={"reviewed": reviewed, "note": note.strip()[:500]},
    )
    return delivery
