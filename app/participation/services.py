import secrets
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import delete, func, select

from app.auth.security import (
    PASSWORDS,
    AuthError,
    check_csrf,
    digest,
    ensure_participation_allowed,
    normalize_email,
    validate_password,
)
from app.auth.services import validate_name
from app.auth.sessions import find_session, new_session, session_user
from app.events.services import PARIS, EventError, authorized_event, organizer_actor
from app.mailer import compose_message
from app.models import (
    Contact,
    Enrollment,
    Event,
    Invitation,
    InvitationResponse,
    InvitationWorkshop,
    MailDelivery,
    Participation,
    ParticipationRequest,
    User,
    Workshop,
)
from app.operations import begin_operation, log_action


def places_for(session, event_id):
    counts = dict(
        session.execute(
            select(Enrollment.workshop_id, func.count())
            .join(
                Participation,
                (Participation.event_id == Enrollment.event_id)
                & (Participation.user_id == Enrollment.user_id),
            )
            .join(User, User.id == Enrollment.user_id)
            .where(
                Enrollment.event_id == event_id,
                Enrollment.status == "active",
                Participation.status == "confirmed",
                User.is_active.is_(True),
                User.role != "super_admin",
            )
            .group_by(Enrollment.workshop_id)
        ).all()
    )
    return {
        w.id: None if w.capacity is None else max(0, w.capacity - counts.get(w.id, 0))
        for w in session.scalars(select(Workshop).where(Workshop.event_id == event_id))
    }


def invitable_contacts(session):
    return list(
        session.scalars(
            select(Contact)
            .outerjoin(User, User.email == Contact.email)
            .where((User.id.is_(None)) | (User.role != "super_admin"))
            .order_by(Contact.name, Contact.id)
        )
    )


def add_contact(session, actor_id, name, email, settings, now):
    organizer_actor(session, actor_id)
    name = validate_name(name)
    email = normalize_email(email, development=settings.environment != "production")
    existing = session.scalar(select(Contact).where(Contact.email == email))
    if existing:
        raise EventError(
            "Cette adresse existe déjà dans le carnet. Sélectionnez le contact existant.",
            409,
        )
    user = session.scalar(select(User).where(User.email == email))
    contact = Contact(
        id=str(uuid4()),
        name=user.name if user else name,
        email=email,
        user_id=user.id if user else None,
        created_at=now,
    )
    session.add(contact)
    session.flush()
    return contact


def _delivery(session, settings, invitation, event, token, now):
    kind = (
        "event_invitation"
        if invitation.purpose == "invitation"
        else "request_verification"
    )
    row = MailDelivery(
        id=str(uuid4()),
        event_id=event.id,
        event_invitation_id=invitation.id,
        user_id=invitation.user_id,
        kind=kind,
        recipient=invitation.email,
        backend=settings.mailer_backend,
        status="pending",
        created_at=now,
    )
    session.add(row)
    session.flush()
    message = compose_message(
        settings,
        row.id,
        invitation.email,
        kind,
        event_name=event.name,
        url=f"{settings.base_url}/invitations#invitation={token}",
        expires=invitation.expires_at.isoformat(),
    )
    row.subject = message.subject
    return row.id, message


def create_invitations(
    session, settings, event_id, actor_id, contact_ids, proposed_ids, now
):
    event = authorized_event(session, event_id, actor_id)
    if event.status != "published":
        raise EventError("Publiez l’événement avant d’envoyer des invitations.", 409)
    contact_ids, proposed_ids = set(contact_ids), set(proposed_ids)
    if not 1 <= len(contact_ids) <= 25:
        raise EventError("Sélectionnez de 1 à 25 contacts.")
    proposed = list(
        session.scalars(
            select(Workshop).where(
                Workshop.id.in_(proposed_ids),
                Workshop.event_id == event.id,
                Workshop.status == "active",
            )
        )
    )
    if len(proposed) != len(proposed_ids):
        raise EventError(
            "Les ateliers proposés doivent appartenir à cet événement et être actifs."
        )
    contacts = list(session.scalars(select(Contact).where(Contact.id.in_(contact_ids))))
    if len(contacts) != len(contact_ids):
        raise EventError("Un contact sélectionné n’existe plus. Rechargez le carnet.")
    deliveries, skipped = [], 0
    for contact in contacts:
        user = session.scalar(select(User).where(User.email == contact.email))
        ensure_participation_allowed(user)
        if user and not user.is_active:
            raise EventError(f"Le compte de {contact.name} est désactivé.")
        invitation = session.scalar(
            select(Invitation).where(
                Invitation.event_id == event.id, Invitation.email == contact.email
            )
        )
        participation = (
            session.get(Participation, (event.id, user.id)) if user else None
        )
        if (participation and participation.status == "confirmed") or (
            invitation
            and invitation.status == "pending"
            and invitation.expires_at > now
        ):
            skipped += 1
            continue
        token = secrets.token_urlsafe(32)
        if invitation is None:
            invitation = Invitation(
                id=str(uuid4()),
                event_id=event.id,
                email=contact.email,
                inviter_id=actor_id,
                user_id=contact.user_id,
                token_digest=digest(token),
                status="pending",
                created_at=now,
                expires_at=now + timedelta(hours=settings.invitation_ttl_hours),
                purpose="invitation",
                invitee_name=contact.name,
            )
            session.add(invitation)
        else:
            (
                invitation.status,
                invitation.token_digest,
                invitation.expires_at,
                invitation.purpose,
            ) = (
                "pending",
                digest(token),
                now + timedelta(hours=settings.invitation_ttl_hours),
                "invitation",
            )
            session.execute(
                delete(InvitationWorkshop).where(
                    InvitationWorkshop.invitation_id == invitation.id
                )
            )
            _invalidate_queued(session, invitation.id)
        session.flush()
        for workshop in proposed:
            session.add(
                InvitationWorkshop(
                    event_id=event.id,
                    invitation_id=invitation.id,
                    workshop_id=workshop.id,
                )
            )
        log_action(
            session,
            event.id,
            actor_id,
            "invitation_created",
            now,
            target_id=invitation.id,
            detail={"email": contact.email},
        )
        deliveries.append(_delivery(session, settings, invitation, event, token, now))
    session.flush()
    return deliveries, skipped


def _invalidate_queued(session, invitation_id):
    for row in session.scalars(
        select(MailDelivery).where(
            MailDelivery.event_invitation_id == invitation_id,
            MailDelivery.status == "pending",
        )
    ):
        row.status, row.error_code = "failed", "invitation_replaced"


def invitation_action(
    session, settings, event_id, actor_id, invitation_id, action, now, operation_id=None
):
    event = authorized_event(session, event_id, actor_id)
    if event.status == "archived":
        raise EventError("Une archive reste en lecture seule.", 409)
    _, fresh = begin_operation(
        session,
        event_id,
        actor_id,
        "invitation_action",
        {"invitation": invitation_id, "action": action},
        now,
        operation_id,
    )
    if not fresh:
        return []
    invitation = session.scalar(
        select(Invitation).where(
            Invitation.id == invitation_id, Invitation.event_id == event_id
        )
    )
    if invitation is None:
        raise EventError("Invitation introuvable.", 404)
    if action == "revoke":
        if invitation.status == "accepted":
            raise EventError(
                "Cette invitation a été acceptée. La participation est conservée.", 409
            )
        if invitation.status != "revoked":
            invitation.status = "revoked"
            _invalidate_queued(session, invitation.id)
            log_action(
                session,
                event_id,
                actor_id,
                "invitation_revoked",
                now,
                target_id=invitation.id,
            )
        return []
    if (
        action != "resend"
        or event.status != "published"
        or invitation.status not in {"pending", "expired"}
    ):
        raise EventError(
            "Cette invitation ne peut pas être relancée dans son état actuel.", 409
        )
    ensure_participation_allowed(
        session.scalar(select(User).where(User.email == invitation.email))
    )
    token = secrets.token_urlsafe(32)
    _invalidate_queued(session, invitation.id)
    invitation.status, invitation.token_digest, invitation.expires_at = (
        "pending",
        digest(token),
        now + timedelta(hours=settings.invitation_ttl_hours),
    )
    log_action(
        session, event_id, actor_id, "invitation_resent", now, target_id=invitation.id
    )
    return [_delivery(session, settings, invitation, event, token, now)]


def prepare_personal_invitation(session, record, token, now):
    ensure_participation_allowed(session_user(session, record))
    if not token or len(token) > 128:
        raise AuthError("Cette invitation n’est pas valide.", 410)
    invitation = session.scalar(
        select(Invitation).where(Invitation.token_digest == digest(token))
    )
    check_personal_invitation(invitation, now)
    ensure_participation_allowed(
        session.scalar(select(User).where(User.email == invitation.email))
    )
    record.pending_event_invitation_id = invitation.id


def check_personal_invitation(invitation, now):
    if (
        invitation is None
        or invitation.status != "pending"
        or invitation.expires_at <= now
    ):
        raise AuthError(
            "Ce lien est expiré, révoqué ou déjà utilisé. Demandez une nouvelle invitation.",
            410,
        )


def personal_context(session, raw_session, now):
    record = find_session(session, raw_session, now)
    if record is None or not record.pending_event_invitation_id:
        raise AuthError("Ouvrez votre lien personnel reçu par e-mail.", 400)
    invitation = session.get(Invitation, record.pending_event_invitation_id)
    check_personal_invitation(invitation, now)
    event = session.get(Event, invitation.event_id)
    if event.status != "published":
        raise AuthError(
            "Cet événement n’accepte plus de réponse à cette invitation.", 409
        )
    existing = session.scalar(select(User).where(User.email == invitation.email))
    ensure_participation_allowed(existing)
    if existing and not existing.is_active:
        raise AuthError("Cet accès est désactivé. Contactez l’organisateur.", 403)
    current = session_user(session, record)
    ensure_participation_allowed(current)
    must_login = bool(
        existing
        and existing.password_hash
        and (not current or current.id != existing.id)
    )
    return record, invitation, event, existing, current, must_login


def validate_enrollments(session, event, user_id, chosen_ids):
    ensure_participation_allowed(session.get(User, user_id))
    ids = set(chosen_ids)
    if len(ids) > 100:
        raise EventError("Choisissez au plus 100 ateliers.")
    selected = list(
        session.scalars(
            select(Workshop)
            .where(
                Workshop.event_id == event.id,
                Workshop.id.in_(ids),
                Workshop.status == "active",
            )
            .order_by(Workshop.starts_at, Workshop.id)
        )
    )
    if len(selected) != len(ids):
        raise EventError(
            "Un atelier sélectionné est annulé ou appartient à un autre événement."
        )
    for workshop in selected:
        count = session.scalar(
            select(func.count())
            .select_from(Enrollment)
            .join(
                Participation,
                (Participation.event_id == Enrollment.event_id)
                & (Participation.user_id == Enrollment.user_id),
            )
            .join(User, User.id == Enrollment.user_id)
            .where(
                Enrollment.workshop_id == workshop.id,
                Enrollment.status == "active",
                Participation.status == "confirmed",
                User.is_active.is_(True),
                Enrollment.user_id != user_id,
            )
        )
        if workshop.capacity is not None and count >= workshop.capacity:
            raise EventError(
                f"L’atelier « {workshop.name} » est complet. Modifiez votre sélection.",
                409,
            )
    outside = list(
        session.scalars(
            select(Workshop)
            .join(Enrollment, Enrollment.workshop_id == Workshop.id)
            .join(
                Participation,
                (Participation.event_id == Enrollment.event_id)
                & (Participation.user_id == Enrollment.user_id),
            )
            .join(Event, Event.id == Workshop.event_id)
            .where(
                Enrollment.user_id == user_id,
                Enrollment.event_id != event.id,
                Enrollment.status == "active",
                Participation.status == "confirmed",
                Workshop.status == "active",
                Event.status == "published",
            )
        )
    )
    for index, workshop in enumerate(selected):
        for other in selected[index + 1 :] + outside:
            if (
                workshop.starts_at < other.ends_at
                and other.starts_at < workshop.ends_at
            ):
                raise EventError(
                    f"« {workshop.name} » chevauche « {other.name} » ({other.starts_at.astimezone(PARIS).strftime('%d/%m/%Y %H:%M')}–{other.ends_at.astimezone(PARIS).strftime('%H:%M')}). Choisissez des créneaux compatibles.",
                    409,
                )
    return selected


def replace_enrollments(session, event, user_id, selected, now):
    ensure_participation_allowed(session.get(User, user_id))
    ids = {w.id for w in selected}
    current = {
        row.workshop_id: row
        for row in session.scalars(
            select(Enrollment).where(
                Enrollment.event_id == event.id, Enrollment.user_id == user_id
            )
        )
    }
    for workshop_id, enrollment in current.items():
        if (
            enrollment.status in {"active", "pending_confirmation"}
            and workshop_id not in ids
        ):
            enrollment.status = "cancelled"
    for workshop in selected:
        if workshop.id in current:
            current[workshop.id].status = "active"
        else:
            session.add(
                Enrollment(
                    event_id=event.id,
                    user_id=user_id,
                    workshop_id=workshop.id,
                    status="active",
                    created_at=now,
                )
            )


def accept_personal_invitation(database, settings, raw_session, form, origin, now):
    with database.sessions() as session:
        record, invitation, _, existing, _, must_login = personal_context(
            session, raw_session, now
        )
        check_csrf(record, form.get("csrf_token", ""), origin, settings.base_url)
        if must_login:
            raise AuthError(
                "Connectez-vous au compte destinataire avant de confirmer.", 403
            )
        existing_id = existing.id if existing else None
        needs_password = existing is None or not existing.password_hash
    hashed, name = None, None
    if needs_password:
        name = validate_name(form.get("name", ""))
        password = form.get("password", "")
        validate_password(password)
        if password != form.get("password_confirmation", ""):
            raise AuthError("Les deux mots de passe ne correspondent pas.", 422)
        hashed = PASSWORDS.hash(password)
    with database.transaction(immediate=True) as session:
        record, invitation, event, existing, _, must_login = personal_context(
            session, raw_session, now
        )
        check_csrf(record, form.get("csrf_token", ""), origin, settings.base_url)
        if (
            must_login
            or (existing.id if existing else None) != existing_id
            or (needs_password and existing and existing.password_hash)
        ):
            raise AuthError(
                "Le compte a changé. Rechargez la page et reconnectez-vous.", 409
            )
        user = existing
        if user is None:
            user = User(
                id=str(uuid4()),
                name=name,
                email=invitation.email,
                password_hash=hashed,
                role="participant",
                created_at=now,
            )
            session.add(user)
            session.flush()
        elif hashed:
            user.name, user.password_hash = name, hashed
        contact = session.scalar(select(Contact).where(Contact.email == user.email))
        if contact is None:
            session.add(
                Contact(
                    id=str(uuid4()),
                    email=user.email,
                    name=user.name,
                    user_id=user.id,
                    created_at=now,
                )
            )
        else:
            contact.user_id = user.id
        if invitation.purpose == "request":
            if event.participation_mode != "open":
                raise EventError("Cet événement n’est plus ouvert aux demandes.", 409)
            _pending_request(session, event, user.id, now)
        else:
            selected = validate_enrollments(
                session, event, user.id, form.get("workshop_ids", [])
            )
            participation = session.get(Participation, (event.id, user.id))
            if participation is None:
                participation = Participation(
                    event_id=event.id,
                    user_id=user.id,
                    status="confirmed",
                    created_at=now,
                )
                session.add(participation)
            else:
                participation.status = "confirmed"
            session.flush()
            replace_enrollments(session, event, user.id, selected, now)
        invitation.status, invitation.user_id = "accepted", user.id
        session.add(
            InvitationResponse(
                id=str(uuid4()),
                event_id=event.id,
                invitation_id=invitation.id,
                actor_id=user.id,
                response="accepted",
                created_at=now,
            )
        )
        log_action(
            session,
            event.id,
            user.id,
            "invitation_accepted"
            if invitation.purpose == "invitation"
            else "request_confirmed",
            now,
            target_id=invitation.id,
        )
        session.delete(record)
        _, token = new_session(session, settings, now, user_id=user.id)
        session.flush()
    return user, token


def decline_personal_invitation(session, raw_session, form, origin, settings, now):
    record, invitation, event, _, current, _ = personal_context(
        session, raw_session, now
    )
    check_csrf(record, form.get("csrf_token", ""), origin, settings.base_url)
    actor_id = current.id if current and current.email == invitation.email else None
    invitation.status = "declined"
    session.add(
        InvitationResponse(
            id=str(uuid4()),
            event_id=event.id,
            invitation_id=invitation.id,
            actor_id=actor_id,
            response="declined",
            created_at=now,
        )
    )
    log_action(
        session,
        event.id,
        actor_id,
        "invitation_declined",
        now,
        target_id=invitation.id,
        detail={"email": invitation.email},
    )
    record.pending_event_invitation_id = None


def _pending_request(session, event, user_id, now):
    ensure_participation_allowed(session.get(User, user_id))
    participation = session.get(Participation, (event.id, user_id))
    if participation and participation.status == "confirmed":
        raise EventError("Votre participation est déjà confirmée.", 409)
    row = session.get(ParticipationRequest, (event.id, user_id))
    if row and row.status == "pending":
        return row
    if row is None:
        row = ParticipationRequest(
            event_id=event.id, user_id=user_id, status="pending", created_at=now
        )
        session.add(row)
    else:
        row.status = "pending"
    log_action(session, event.id, user_id, "request_created", now)
    return row


def public_request(session, settings, event, user, email, name, now):
    ensure_participation_allowed(user)
    if event.status != "published" or event.participation_mode != "open":
        raise EventError("Cet événement n’accepte pas de demande publique.", 404)
    if user:
        _pending_request(session, event, user.id, now)
        return []
    email = normalize_email(email, development=settings.environment != "production")
    name = validate_name(name)
    existing = session.scalar(select(User).where(User.email == email))
    if existing and (existing.role == "super_admin" or not existing.is_active):
        return []  # Même réponse neutre, sans envoyer d’invitation à un compte de gestion.
    invitation = session.scalar(
        select(Invitation).where(
            Invitation.event_id == event.id, Invitation.email == email
        )
    )
    if invitation and (
        invitation.status == "accepted"
        or (invitation.status == "pending" and invitation.expires_at > now)
    ):
        return []  # Même réponse neutre : pas d’énumération des comptes ou de relance anonyme.
    token = secrets.token_urlsafe(32)
    if invitation is None:
        invitation = Invitation(
            id=str(uuid4()),
            event_id=event.id,
            email=email,
            inviter_id=event.owner_id,
            token_digest=digest(token),
            purpose="request",
            invitee_name=name,
            status="pending",
            created_at=now,
            expires_at=now + timedelta(hours=settings.invitation_ttl_hours),
        )
        session.add(invitation)
    else:
        invitation.purpose, invitation.status, invitation.invitee_name = (
            "request",
            "pending",
            name,
        )
        invitation.token_digest, invitation.expires_at = (
            digest(token),
            now + timedelta(hours=settings.invitation_ttl_hours),
        )
        _invalidate_queued(session, invitation.id)
    session.flush()
    return [_delivery(session, settings, invitation, event, token, now)]


def decide_request(session, settings, event_id, actor_id, user_id, accepted, now):
    event = authorized_event(session, event_id, actor_id)
    if event.status != "published":
        raise EventError("Cet événement ne reçoit plus de participations.", 409)
    request = session.get(ParticipationRequest, (event_id, user_id))
    user = session.get(User, user_id)
    if request is None or user is None:
        raise EventError("Demande introuvable.", 404)
    desired = "accepted" if accepted else "declined"
    if request.status == desired:
        return []
    if request.status != "pending":
        raise EventError("Cette demande a déjà été traitée.", 409)
    if not user.is_active:
        raise EventError("Ce compte est désactivé.", 409)
    if accepted:
        ensure_participation_allowed(user)
    request.status = desired
    if accepted:
        participation = session.get(Participation, (event_id, user_id))
        if participation is None:
            session.add(
                Participation(
                    event_id=event_id,
                    user_id=user_id,
                    status="confirmed",
                    created_at=now,
                )
            )
        else:
            participation.status = "confirmed"
    content = (
        "Votre demande a été acceptée. Vous pouvez maintenant choisir vos ateliers."
        if accepted
        else "Votre demande de participation a été refusée par l’organisateur."
    )
    row = MailDelivery(
        id=str(uuid4()),
        event_id=event_id,
        user_id=user_id,
        kind="request_response",
        recipient=user.email,
        backend=settings.mailer_backend,
        status="pending",
        created_at=now,
    )
    session.add(row)
    session.flush()
    log_action(
        session,
        event_id,
        actor_id,
        "request_accepted" if accepted else "request_declined",
        now,
        target_id=user_id,
    )
    message = compose_message(
        settings,
        row.id,
        user.email,
        "request_response",
        event_name=event.name,
        content=content,
    )
    row.subject = message.subject
    row.context = {
        "subject": message.subject,
        "html": message.html,
        "text": message.text,
    }
    return [(row.id, message)]
