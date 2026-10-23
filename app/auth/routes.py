from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from app.auth.http import (
    Identity,
    checked_user,
    current_identity,
    ensure_form_identity,
    form_context,
    home_for,
    read_form,
    render,
    required_user,
)
from app.auth.security import AuthError, check_csrf
from app.auth.services import (
    accept_invitation,
    authenticate,
    change_access,
    consume_limit,
    create_invitation,
    invitation_context,
    prepare_invitation,
    revoke_invitation,
)
from app.auth.sessions import (
    clear_cookie,
    find_session,
    set_cookie,
)
from app.mailer import MemoryMailer
from app.models import (
    AuthAudit,
    Event,
    MailDelivery,
    OrganizerInvitation,
    Participation,
    ParticipationRequest,
    User,
)


def router():
    result = APIRouter()
    destinations = {
        "invitation": "/activation-organisateur",
        "evenement": "/invitations",
    }

    @result.get("/connexion", name="login")
    def login_page(request: Request):
        identity, token = ensure_form_identity(request)
        following = request.query_params.get("suivant", "")
        following = following if following in destinations else ""
        if identity.user:
            return RedirectResponse(
                destinations.get(following, home_for(identity.user)),
                status_code=303,
            )
        return render(
            request,
            "auth/login.html",
            identity,
            token=token,
            error=None,
            email="",
            following=following,
        )

    @result.post("/connexion")
    def login_submit(request: Request, form: Annotated[dict, Depends(read_form)]):
        try:
            user, token = authenticate(
                request.app.state.database,
                request.app.state.settings,
                request.cookies.get(request.app.state.settings.cookie_name),
                form,
                request.headers.get("origin"),
                request.client.host if request.client else "unknown",
                request.app.state.clock(),
            )
        except AuthError as error:
            identity, token = ensure_form_identity(request)
            response = render(
                request,
                "auth/login.html",
                identity,
                status=error.status,
                token=token,
                error=str(error),
                email=form.get("email", "")[:254],
                following=form.get("following", "")
                if form.get("following") in destinations
                else "",
            )
            if error.status == 429:
                response.headers["Retry-After"] = "900"
            return response
        response = RedirectResponse(
            destinations.get(form.get("following"), home_for(user)),
            status_code=303,
        )
        set_cookie(
            response,
            request.app.state.settings,
            token,
            request.app.state.settings.session_ttl_seconds,
        )
        return response

    @result.post("/deconnexion", name="logout")
    def logout(request: Request, form: Annotated[dict, Depends(read_form)]):
        database, settings = request.app.state.database, request.app.state.settings
        with database.transaction(immediate=True) as session:
            record = find_session(
                session,
                request.cookies.get(settings.cookie_name),
                request.app.state.clock(),
            )
            if record:
                check_csrf(
                    record,
                    form.get("csrf_token", ""),
                    request.headers.get("origin"),
                    settings.base_url,
                )
                session.delete(record)
        response = RedirectResponse("/", status_code=303)
        clear_cookie(response, settings)
        return response

    @result.get("/admin", name="admin")
    def admin(
        request: Request, identity: Annotated[Identity, Depends(current_identity)]
    ):
        if response := required_user(identity, "super_admin"):
            return response
        with request.app.state.database.sessions() as session:
            users = list(
                session.scalars(
                    select(User).where(User.role == "organizer").order_by(User.name)
                )
            )
            invitations = list(
                session.scalars(
                    select(OrganizerInvitation).order_by(
                        OrganizerInvitation.created_at.desc()
                    )
                )
            )
            deliveries = {
                d.invitation_id: d for d in session.scalars(select(MailDelivery))
            }
            audit = list(
                session.scalars(
                    select(AuthAudit).order_by(AuthAudit.created_at.desc()).limit(15)
                )
            )
        return render(
            request,
            "auth/admin.html",
            identity,
            users=users,
            invitations=invitations,
            deliveries=deliveries,
            audit=audit,
            now=request.app.state.clock(),
            local_mail=isinstance(request.app.state.mailer, MemoryMailer),
            error=None,
        )

    @result.post("/admin/invitations", name="invite_organizer")
    def invite(
        request: Request,
        form: Annotated[dict, Depends(read_form)],
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_user(identity, "super_admin"):
            return response
        form_context(request, identity, form)
        consume_limit(
            request.app.state.database,
            [(f"invite-admin:{identity.user.id}", 20)],
            request.app.state.clock(),
        )
        with request.app.state.database.transaction(immediate=True) as session:
            actor = checked_user(request, session, form, "super_admin")
            invitation, _delivery, token = create_invitation(
                session,
                request.app.state.settings,
                actor.id,
                form.get("email", ""),
                request.app.state.clock(),
            )
            invitation_id = invitation.id
        request.app.state.scheduler.submit_organizer(invitation_id, token)
        return RedirectResponse("/admin", status_code=303)

    @result.post(
        "/admin/invitations/{invitation_id}/revoquer", name="revoke_invitation"
    )
    def revoke(
        request: Request,
        invitation_id: str,
        form: Annotated[dict, Depends(read_form)],
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_user(identity, "super_admin"):
            return response
        form_context(request, identity, form)
        with request.app.state.database.transaction(immediate=True) as session:
            actor = checked_user(request, session, form, "super_admin")
            revoke_invitation(
                session, actor.id, invitation_id, request.app.state.clock()
            )
        return RedirectResponse("/admin", status_code=303)

    @result.post("/admin/organisateurs/{user_id}/{action}", name="organizer_access")
    def access(
        request: Request,
        user_id: str,
        action: str,
        form: Annotated[dict, Depends(read_form)],
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_user(identity, "super_admin"):
            return response
        form_context(request, identity, form)
        if action not in {"desactiver", "reactiver"}:
            raise AuthError("Action introuvable.", 404)
        with request.app.state.database.transaction(immediate=True) as session:
            actor = checked_user(request, session, form, "super_admin")
            change_access(
                session,
                actor.id,
                user_id,
                action == "reactiver",
                request.app.state.clock(),
            )
        return RedirectResponse("/admin", status_code=303)

    @result.get("/admin/courriers-locaux", name="local_mailbox")
    def mailbox(
        request: Request, identity: Annotated[Identity, Depends(current_identity)]
    ):
        if response := required_user(identity, "super_admin"):
            return response
        if request.app.state.settings.environment == "production" or not isinstance(
            request.app.state.mailer, MemoryMailer
        ):
            raise AuthError("Page introuvable.", 404)
        return render(
            request,
            "auth/mailbox.html",
            identity,
            messages=request.app.state.mailer.messages,
        )

    @result.get("/activation-organisateur", name="activate_organizer")
    def activation(request: Request):
        identity, token = ensure_form_identity(request)
        with request.app.state.database.sessions() as session:
            try:
                _record, invitation, existing, current = invitation_context(
                    session,
                    request.cookies.get(request.app.state.settings.cookie_name),
                    request.app.state.clock(),
                )
                needs_password = existing is None or not existing.password_hash
                must_login = bool(
                    existing and existing.password_hash and current is None
                )
            except AuthError as error:
                return render(
                    request,
                    "auth/activation.html",
                    identity,
                    token=token,
                    error=str(error) if identity.record.pending_invitation_id else None,
                    invitation=None,
                    needs_password=False,
                    must_login=False,
                    status=error.status
                    if identity.record.pending_invitation_id
                    else 200,
                    name="",
                )
        return render(
            request,
            "auth/activation.html",
            identity,
            token=token,
            error=None,
            invitation=invitation,
            needs_password=needs_password,
            must_login=must_login,
            name=existing.name if existing else "",
        )

    @result.post("/activation-organisateur/preparer", name="prepare_organizer")
    def prepare(
        request: Request,
        form: Annotated[dict, Depends(read_form)],
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        form_context(request, identity, form)
        consume_limit(
            request.app.state.database,
            [
                (
                    f"invite-token:{request.client.host if request.client else 'unknown'}",
                    20,
                )
            ],
            request.app.state.clock(),
        )
        with request.app.state.database.transaction(immediate=True) as session:
            record = find_session(
                session,
                request.cookies.get(request.app.state.settings.cookie_name),
                request.app.state.clock(),
            )
            check_csrf(
                record,
                form.get("csrf_token", ""),
                request.headers.get("origin"),
                request.app.state.settings.base_url,
            )
            prepare_invitation(
                session, record, form.get("token", ""), request.app.state.clock()
            )
        return JSONResponse({"ready": True}, headers={"Cache-Control": "no-store"})

    @result.post("/activation-organisateur")
    def activation_submit(request: Request, form: Annotated[dict, Depends(read_form)]):
        consume_limit(
            request.app.state.database,
            [
                (
                    f"activate-ip:{request.client.host if request.client else 'unknown'}",
                    10,
                )
            ],
            request.app.state.clock(),
        )
        user, token = accept_invitation(
            request.app.state.database,
            request.app.state.settings,
            request.cookies.get(request.app.state.settings.cookie_name),
            form,
            request.headers.get("origin"),
            request.app.state.clock(),
        )
        response = RedirectResponse(home_for(user), status_code=303)
        set_cookie(
            response,
            request.app.state.settings,
            token,
            request.app.state.settings.session_ttl_seconds,
        )
        return response

    @result.get("/espace", name="participant_space")
    def participant(
        request: Request, identity: Annotated[Identity, Depends(current_identity)]
    ):
        if response := required_user(identity):
            return response
        with request.app.state.database.sessions() as session:
            events = list(
                session.scalars(
                    select(Event)
                    .join(Participation, Participation.event_id == Event.id)
                    .where(
                        Participation.user_id == identity.user.id,
                        Participation.status == "confirmed",
                    )
                    .order_by(Event.starts_at)
                )
            )
            requests = list(
                session.execute(
                    select(ParticipationRequest, Event)
                    .join(Event, Event.id == ParticipationRequest.event_id)
                    .where(ParticipationRequest.user_id == identity.user.id)
                    .order_by(ParticipationRequest.created_at.desc())
                )
            )
        return render(
            request,
            "auth/participant.html",
            identity,
            events=events,
            participation_requests=requests,
        )

    return result
