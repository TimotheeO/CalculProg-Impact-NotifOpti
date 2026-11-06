"""Récupération par lien à usage unique ; aucun secret de lien persisté en clair."""

import secrets
from datetime import timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import delete, select

from app.auth.http import ensure_form_identity, read_form, render, transaction_identity
from app.auth.security import (
    PASSWORDS,
    AuthError,
    digest,
    normalize_email,
    validate_password,
)
from app.auth.services import audit, consume_limit
from app.auth.sessions import clear_cookie, find_session
from app.mailer import compose_message
from app.models import AuthSession, MailDelivery, PasswordReset, User


def valid_reset(session, reset, now):
    if reset is None or reset.used_at is not None or reset.expires_at <= now:
        raise AuthError(
            "Ce lien de récupération est invalide, expiré ou déjà utilisé.", 410
        )
    user = session.get(User, reset.user_id)
    if user is None or not user.is_active:
        raise AuthError("Ce lien de récupération n’est plus utilisable.", 410)
    return user


def request_reset(session, settings, email, now):
    email = normalize_email(email, development=settings.environment != "production")
    user = session.scalar(
        select(User).where(User.email == email, User.is_active.is_(True))
    )
    if user is None or not user.password_hash:
        return None
    for old in session.scalars(
        select(PasswordReset).where(
            PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None)
        )
    ):
        old.used_at = now
    token = secrets.token_urlsafe(32)
    reset = PasswordReset(
        id=str(uuid4()),
        user_id=user.id,
        token_digest=digest(token),
        created_at=now,
        expires_at=now + timedelta(minutes=30),
    )
    session.add(reset)
    session.flush()
    delivery = MailDelivery(
        id=str(uuid4()),
        user_id=user.id,
        password_reset_id=reset.id,
        kind="password_reset",
        recipient=user.email,
        backend=settings.mailer_backend,
        status="pending",
        created_at=now,
    )
    session.add(delivery)
    session.flush()
    message = compose_message(
        settings,
        delivery.id,
        user.email,
        "password_reset",
        url=f"{settings.base_url}/reinitialisation#reset={token}",
        expires=reset.expires_at.isoformat(),
    )
    delivery.subject = message.subject
    audit(session, "password_reset_requested", now, target_user_id=user.id)
    return delivery.id, message


def router():
    result = APIRouter()

    def reset_page(request, *, error=None, status=200):
        identity, token = ensure_form_identity(request)
        target = None
        if identity.record.pending_password_reset_id:
            with request.app.state.database.sessions() as session:
                try:
                    target = valid_reset(
                        session,
                        session.get(
                            PasswordReset, identity.record.pending_password_reset_id
                        ),
                        request.app.state.clock(),
                    )
                except AuthError as issue:
                    error, status = issue, issue.status
        return render(
            request,
            "auth/reset.html",
            identity,
            token=token,
            target=target,
            error=str(error) if error else None,
            status=status,
        )

    @result.get("/mot-de-passe-oublie")
    def forgotten(request: Request):
        identity, token = ensure_form_identity(request)
        return render(request, "auth/forgotten.html", identity, token=token, sent=False)

    @result.post("/mot-de-passe-oublie")
    def send(request: Request, form: Annotated[dict, Depends(read_form)]):
        now, settings, database = (
            request.app.state.clock(),
            request.app.state.settings,
            request.app.state.database,
        )
        consume_limit(
            database,
            [
                (f"recovery-ip:{request.client.host}", 10),
                (f"recovery-email:{form.get('email', '').strip().casefold()}", 3),
            ],
            now,
        )
        with database.transaction(immediate=True) as session:
            identity = transaction_identity(request, session, form)
            delivery = request_reset(session, settings, form.get("email", ""), now)
        if delivery:
            request.app.state.scheduler.submit(*delivery)
        return render(request, "auth/forgotten.html", identity, sent=True)

    @result.get("/reinitialisation")
    def reset(request: Request):
        return reset_page(request)

    @result.post("/reinitialisation/preparer")
    def prepare(request: Request, form: Annotated[dict, Depends(read_form)]):
        database, now = request.app.state.database, request.app.state.clock()
        consume_limit(database, [(f"reset-token:{request.client.host}", 20)], now)
        raw = form.get("token", "")
        if not raw or len(raw) > 128:
            raise AuthError("Lien de récupération invalide.", 410)
        with database.transaction(immediate=True) as session:
            identity = transaction_identity(request, session, form)
            reset = session.scalar(
                select(PasswordReset).where(PasswordReset.token_digest == digest(raw))
            )
            valid_reset(session, reset, now)
            identity.record.pending_password_reset_id = reset.id
        return JSONResponse({"prepared": True})

    @result.post("/reinitialisation")
    def save(request: Request, form: Annotated[dict, Depends(read_form)]):
        database, settings, now = (
            request.app.state.database,
            request.app.state.settings,
            request.app.state.clock(),
        )
        try:
            consume_limit(database, [(f"reset-save:{request.client.host}", 20)], now)
            with database.sessions() as session:
                transaction_identity(request, session, form)
            password = form.get("password", "")
            validate_password(password)
            if password != form.get("password_confirmation", ""):
                raise AuthError("Les deux mots de passe ne correspondent pas.", 422)
            hashed = PASSWORDS.hash(password)
            with database.transaction(immediate=True) as session:
                transaction_identity(request, session, form)
                record = find_session(
                    session, request.cookies.get(settings.cookie_name), now
                )
                reset = (
                    session.get(PasswordReset, record.pending_password_reset_id)
                    if record and record.pending_password_reset_id
                    else None
                )
                user = valid_reset(session, reset, now)
                user.password_hash = hashed
                resets = list(
                    session.scalars(
                        select(PasswordReset).where(PasswordReset.user_id == user.id)
                    )
                )
                for previous in resets:
                    previous.used_at = previous.used_at or now
                session.execute(
                    delete(AuthSession).where(
                        (AuthSession.user_id == user.id)
                        | AuthSession.pending_password_reset_id.in_(
                            [r.id for r in resets]
                        )
                    )
                )
                audit(
                    session,
                    "password_reset_completed",
                    now,
                    actor_id=user.id,
                    target_user_id=user.id,
                )
        except AuthError as error:
            return reset_page(request, error=error, status=error.status)
        response = RedirectResponse("/connexion?mot-de-passe=modifie", status_code=303)
        clear_cookie(response, settings)
        return response

    return result
