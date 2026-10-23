import secrets
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import delete, select, update

from app.auth.security import (
    PASSWORDS,
    AuthError,
    check_csrf,
    digest,
    normalize_email,
    password_matches,
    validate_password,
)
from app.auth.sessions import find_session, new_session, session_user
from app.models import (
    AuthAudit,
    AuthRateLimit,
    AuthSession,
    Contact,
    MailDelivery,
    OrganizerInvitation,
    User,
)


def audit(
    session, action, now, *, actor_id=None, target_user_id=None, invitation_id=None
):
    session.add(
        AuthAudit(
            id=str(uuid4()),
            action=action,
            actor_id=actor_id,
            target_user_id=target_user_id,
            invitation_id=invitation_id,
            created_at=now,
        )
    )


def require_superadmin(session, actor_id):
    actor = session.get(User, actor_id)
    if actor is None or not actor.is_active or actor.role != "super_admin":
        raise AuthError("Cette action est réservée au super-admin.", 403)
    return actor


def validate_name(name):
    name = name.strip()
    if not 1 <= len(name) <= 120:
        raise AuthError("Le nom doit contenir entre 1 et 120 caractères.", 422)
    return name


def bootstrap_admin(database, settings, email, name, password, now):
    email = normalize_email(email, development=settings.environment != "production")
    name = validate_name(name)
    validate_password(password)
    hashed = PASSWORDS.hash(password)
    with database.transaction(immediate=True) as session:
        if (
            session.scalar(select(User.id).where(User.role == "super_admin"))
            is not None
        ):
            raise AuthError(
                "Un super-admin existe déjà. Cette commande initialise uniquement le premier compte.",
                409,
            )
        if session.scalar(select(User.id).where(User.email == email)) is not None:
            raise AuthError(
                "Un compte utilise déjà cette adresse. Aucun rôle n’a été modifié.", 409
            )
        user = User(
            id=str(uuid4()),
            email=email,
            name=name,
            role="super_admin",
            password_hash=hashed,
            created_at=now,
        )
        session.add(user)
        session.flush()
        session.add(
            Contact(
                id=str(uuid4()), email=email, name=name, user_id=user.id, created_at=now
            )
        )
        audit(session, "bootstrap_admin", now, actor_id=user.id, target_user_id=user.id)
    return user


def consume_limit(database, keys, now, *, seconds=900):
    with database.transaction(immediate=True) as session:
        for label, maximum in keys:
            key = digest(label)
            record = session.get(AuthRateLimit, key)
            if record is None:
                session.add(AuthRateLimit(key=key, attempts=1, window_started_at=now))
            elif record.window_started_at + timedelta(seconds=seconds) <= now:
                record.window_started_at, record.attempts = now, 1
            elif record.attempts >= maximum:
                raise AuthError(
                    "Trop de tentatives. Réessayez dans quinze minutes.", 429
                )
            else:
                record.attempts += 1


def authenticate(database, settings, token, form, origin, ip, now):
    with database.sessions() as session:
        record = find_session(session, token, now)
        check_csrf(record, form.get("csrf_token", ""), origin, settings.base_url)
    email = form.get("email", "").strip().casefold()
    pair_key = f"login-pair:{ip}:{email}"
    consume_limit(database, [(f"login-ip:{ip}", 30), (pair_key, 5)], now)
    with database.sessions() as session:
        user = session.scalar(select(User).where(User.email == email))
        stored = user.password_hash if user else None
    valid = password_matches(stored, form.get("password", ""))
    if not valid or user is None or not user.is_active:
        raise AuthError("Adresse e-mail ou mot de passe incorrect.", 401)
    replacement = (
        PASSWORDS.hash(form["password"])
        if PASSWORDS.check_needs_rehash(stored)
        else None
    )
    with database.transaction(immediate=True) as session:
        record = find_session(session, token, now)
        check_csrf(record, form.get("csrf_token", ""), origin, settings.base_url)
        current = session.get(User, user.id)
        if current is None or not current.is_active or current.password_hash != stored:
            raise AuthError("Adresse e-mail ou mot de passe incorrect.", 401)
        if replacement:
            current.password_hash = replacement
        pending = record.pending_invitation_id
        pending_event = record.pending_event_invitation_id
        session.delete(record)
        _, new_token = new_session(
            session,
            settings,
            now,
            user_id=current.id,
            pending_invitation_id=pending,
            pending_event_invitation_id=pending_event,
        )
        session.execute(
            delete(AuthRateLimit).where(AuthRateLimit.key == digest(pair_key))
        )
        audit(session, "login", now, actor_id=current.id, target_user_id=current.id)
    return current, new_token


def create_invitation(session, settings, actor_id, email, now):
    require_superadmin(session, actor_id)
    email = normalize_email(email, development=settings.environment != "production")
    user = session.scalar(select(User).where(User.email == email))
    if user and (
        not user.is_active
        or user.role == "super_admin"
        or (user.role == "organizer" and user.password_hash)
    ):
        raise AuthError(
            "Ce compte ne peut pas recevoir une nouvelle invitation organisateur. Vérifiez son rôle et son accès.",
            409,
        )
    session.execute(
        update(OrganizerInvitation)
        .where(
            OrganizerInvitation.email == email,
            OrganizerInvitation.status == "pending",
            OrganizerInvitation.expires_at <= now,
        )
        .values(status="expired")
    )
    if session.scalar(
        select(OrganizerInvitation.id).where(
            OrganizerInvitation.email == email,
            OrganizerInvitation.status == "pending",
        )
    ):
        raise AuthError(
            "Une invitation valide est déjà en attente pour cette adresse.", 409
        )
    token = secrets.token_urlsafe(32)
    invitation = OrganizerInvitation(
        id=str(uuid4()),
        email=email,
        inviter_id=actor_id,
        token_digest=digest(token),
        status="pending",
        created_at=now,
        expires_at=now + timedelta(hours=settings.invitation_ttl_hours),
    )
    session.add(invitation)
    session.flush()
    delivery = MailDelivery(
        id=str(uuid4()),
        invitation_id=invitation.id,
        backend=settings.mailer_backend,
        status="pending",
        created_at=now,
    )
    session.add(delivery)
    audit(
        session, "invite_organizer", now, actor_id=actor_id, invitation_id=invitation.id
    )
    session.flush()
    return invitation, delivery, token


def check_invitation(invitation, now):
    if (
        invitation is None
        or invitation.status != "pending"
        or invitation.expires_at <= now
    ):
        raise AuthError(
            "Cette invitation est invalide, expirée ou déjà utilisée. Demandez une nouvelle invitation au super-admin.",
            410,
        )


def prepare_invitation(session, record, token, now):
    if not token or len(token) > 128:
        raise AuthError("Cette invitation n’est pas valide.", 410)
    invitation = session.scalar(
        select(OrganizerInvitation).where(
            OrganizerInvitation.token_digest == digest(token)
        )
    )
    check_invitation(invitation, now)
    record.pending_invitation_id = invitation.id
    return invitation


def invitation_context(session, raw_token, now):
    record = find_session(session, raw_token, now)
    if record is None or record.pending_invitation_id is None:
        raise AuthError("Ouvrez le lien personnel reçu dans votre invitation.", 400)
    invitation = session.get(OrganizerInvitation, record.pending_invitation_id)
    check_invitation(invitation, now)
    existing = session.scalar(select(User).where(User.email == invitation.email))
    current = session_user(session, record)
    if existing and not existing.is_active:
        raise AuthError("Cet accès est désactivé. Contactez le super-admin.", 403)
    if (
        existing
        and existing.password_hash
        and (current is None or current.id != existing.id)
    ):
        return record, invitation, existing, None
    return record, invitation, existing, current


def accept_invitation(database, settings, raw_token, form, origin, now):
    with database.sessions() as session:
        record, invitation, existing, current = invitation_context(
            session, raw_token, now
        )
        check_csrf(record, form.get("csrf_token", ""), origin, settings.base_url)
        if existing and existing.password_hash and current is None:
            raise AuthError(
                "Connectez-vous avec le compte destinataire pour accepter cette invitation.",
                403,
            )
        existing_id = existing.id if existing else None
        requires_password = existing is None or existing.password_hash is None
    name = validate_name(form.get("name", "")) if requires_password else None
    hashed = None
    if requires_password:
        password = form.get("password", "")
        validate_password(password)
        if password != form.get("password_confirmation", ""):
            raise AuthError("Les deux mots de passe ne correspondent pas.", 422)
        hashed = PASSWORDS.hash(password)
    with database.transaction(immediate=True) as session:
        record, invitation, existing, current = invitation_context(
            session, raw_token, now
        )
        check_csrf(record, form.get("csrf_token", ""), origin, settings.base_url)
        if (existing.id if existing else None) != existing_id or (
            existing and existing.password_hash and requires_password
        ):
            raise AuthError(
                "Le compte a changé. Rechargez la page et reconnectez-vous.", 409
            )
        if existing and existing.password_hash and current is None:
            raise AuthError("Connectez-vous avec le compte destinataire.", 403)
        if existing and existing.role == "super_admin":
            raise AuthError("Le rôle de ce compte ne peut pas être remplacé.", 409)
        if existing is None:
            existing = User(
                id=str(uuid4()),
                email=invitation.email,
                name=name,
                role="organizer",
                password_hash=hashed,
                created_at=now,
            )
            session.add(existing)
            session.flush()
        else:
            existing.role = "organizer"
            if hashed:
                existing.password_hash, existing.name = hashed, name
        contact = session.scalar(select(Contact).where(Contact.email == existing.email))
        if contact is None:
            session.add(
                Contact(
                    id=str(uuid4()),
                    email=existing.email,
                    name=existing.name,
                    user_id=existing.id,
                    created_at=now,
                )
            )
        else:
            contact.user_id, contact.name = existing.id, existing.name
        invitation.status, invitation.accepted_at, invitation.accepted_user_id = (
            "accepted",
            now,
            existing.id,
        )
        session.execute(delete(AuthSession).where(AuthSession.user_id == existing.id))
        if record.user_id != existing.id:
            session.delete(record)
        _, new_token = new_session(session, settings, now, user_id=existing.id)
        audit(
            session,
            "accept_organizer_invite",
            now,
            actor_id=existing.id,
            target_user_id=existing.id,
            invitation_id=invitation.id,
        )
        session.flush()
    return existing, new_token


def revoke_invitation(session, actor_id, invitation_id, now):
    require_superadmin(session, actor_id)
    invitation = session.get(OrganizerInvitation, invitation_id)
    if invitation is None:
        raise AuthError("Invitation introuvable.", 404)
    if invitation.status == "accepted":
        raise AuthError(
            "Cette invitation a été acceptée. Désactivez l’accès du compte si nécessaire.",
            409,
        )
    if invitation.status == "pending":
        invitation.status = "revoked"
        audit(
            session,
            "revoke_organizer_invite",
            now,
            actor_id=actor_id,
            invitation_id=invitation_id,
        )


def change_access(session, actor_id, target_id, active, now):
    require_superadmin(session, actor_id)
    target = session.get(User, target_id)
    if target is None or target.role != "organizer" or target.id == actor_id:
        raise AuthError("Compte organisateur introuvable.", 404)
    if target.is_active != active:
        target.is_active = active
        session.execute(delete(AuthSession).where(AuthSession.user_id == target_id))
        audit(
            session,
            "enable_organizer" if active else "disable_organizer",
            now,
            actor_id=actor_id,
            target_user_id=target_id,
        )
