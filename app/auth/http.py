"""Identité, formulaires bornés et rendu partagés par les espaces web."""

from dataclasses import dataclass
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import RedirectResponse

from app.auth.security import AuthError, check_csrf
from app.auth.sessions import find_session, new_session, session_user, set_cookie
from app.models import AuthSession, User


@dataclass
class Identity:
    record: AuthSession | None
    user: User | None


def current_identity(request: Request):
    database, settings = request.app.state.database, request.app.state.settings
    with database.sessions() as session:
        record = find_session(
            session,
            request.cookies.get(settings.cookie_name),
            request.app.state.clock(),
        )
        return Identity(record, session_user(session, record))


def ensure_form_identity(request):
    database, settings = request.app.state.database, request.app.state.settings
    with database.transaction(immediate=True) as session:
        record = find_session(
            session,
            request.cookies.get(settings.cookie_name),
            request.app.state.clock(),
        )
        user = session_user(session, record)
        token = None
        if record is None or (record.user_id and user is None):
            if record is not None:
                session.delete(record)
            record, token = new_session(session, settings, request.app.state.clock())
        return Identity(record, user), token


async def read_urlencoded(
    request: Request, *, max_bytes=16384, multiple_fields=(), max_fields=12
):
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip()
        != "application/x-www-form-urlencoded"
    ):
        raise AuthError("Format de formulaire non pris en charge.", 415)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > max_bytes:
            raise AuthError("Le formulaire est trop volumineux.", 413)
        body.extend(chunk)
    try:
        parsed = parse_qs(
            body.decode("utf-8"),
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
            max_num_fields=max_fields,
        )
    except (UnicodeError, ValueError) as error:
        raise AuthError("Le formulaire n’est pas valide.", 400) from error
    if any(
        len(values) != 1 for key, values in parsed.items() if key not in multiple_fields
    ):
        raise AuthError("Le formulaire contient un champ répété.", 400)
    return {
        key: values if key in multiple_fields else values[0]
        for key, values in parsed.items()
    }


def home_for(user):
    return (
        "/admin"
        if user.role == "super_admin"
        else "/organisateur"
        if user.role == "organizer"
        else "/espace"
    )


def required_user(identity, role=None):
    if identity.user is None:
        return RedirectResponse("/connexion", status_code=303)
    if role and identity.user.role != role:
        raise AuthError("Votre compte n’a pas accès à cet espace.", 403)
    return None


def form_context(request, identity, form):
    check_csrf(
        identity.record,
        form.get("csrf_token", ""),
        request.headers.get("origin"),
        request.app.state.settings.base_url,
    )


def transaction_identity(request, session, form):
    settings = request.app.state.settings
    record = find_session(
        session, request.cookies.get(settings.cookie_name), request.app.state.clock()
    )
    check_csrf(
        record,
        form.get("csrf_token", ""),
        request.headers.get("origin"),
        settings.base_url,
    )
    return Identity(record, session_user(session, record))


def checked_user(request, session, form, role=None):
    identity = transaction_identity(request, session, form)
    if identity.user is None or (role and identity.user.role != role):
        raise AuthError(
            "Votre session ou vos droits ne permettent plus cette action. Reconnectez-vous.",
            403,
        )
    return identity.user


def render(request, template, identity, *, status=200, token=None, **values):
    response = request.app.state.templates.TemplateResponse(
        request=request,
        name=template,
        context={
            "viewer": identity.user,
            "csrf_token": identity.record.csrf_token if identity.record else "",
            **values,
        },
        status_code=status,
    )
    if token:
        ttl = request.app.state.settings.session_ttl_seconds if identity.user else 1800
        set_cookie(response, request.app.state.settings, token, ttl)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


async def read_form(request: Request):
    return await read_urlencoded(request)


async def read_event_form(request: Request):
    return await read_urlencoded(request, max_bytes=65536)


async def read_selection(request: Request):
    return await read_urlencoded(
        request,
        max_bytes=65536,
        max_fields=256,
        multiple_fields={"contact_ids", "workshop_ids"},
    )
