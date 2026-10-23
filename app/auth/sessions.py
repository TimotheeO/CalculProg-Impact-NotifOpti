import secrets
from datetime import timedelta

from app.auth.security import digest
from app.models import AuthSession, User


def find_session(session, token, now):
    if not token or len(token) > 128:
        return None
    record = session.get(AuthSession, digest(token))
    return record if record is not None and record.expires_at > now else None


def session_user(session, record):
    if record is None or record.user_id is None:
        return None
    user = session.get(User, record.user_id)
    return user if user is not None and user.is_active else None


def new_session(
    session,
    settings,
    now,
    *,
    user_id=None,
    pending_invitation_id=None,
    pending_event_invitation_id=None,
):
    token = secrets.token_urlsafe(32)
    record = AuthSession(
        token_digest=digest(token),
        user_id=user_id,
        csrf_token=secrets.token_urlsafe(32),
        created_at=now,
        expires_at=now
        + timedelta(seconds=settings.session_ttl_seconds if user_id else 1800),
        pending_invitation_id=pending_invitation_id,
        pending_event_invitation_id=pending_event_invitation_id,
    )
    session.add(record)
    session.flush()
    return record, token


def set_cookie(response, settings, token, ttl):
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=ttl,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def clear_cookie(response, settings):
    response.delete_cookie(
        settings.cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
