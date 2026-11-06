"""Invitations personnelles, carnet partagé et demandes vérifiées par e-mail."""

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
    ensure_form_identity,
    form_context,
    read_selection,
    render,
    required_participant,
    required_user,
    transaction_identity,
)
from app.auth.security import AuthError, ensure_participation_allowed
from app.auth.services import consume_limit
from app.auth.sessions import set_cookie
from app.events.services import EventError, authorized_event, workshops_for
from app.models import (
    Contact,
    Enrollment,
    Event,
    Invitation,
    InvitationWorkshop,
    Participation,
)
from app.notification_groups import recalculate_pending
from app.operations import log_action
from app.participation import services


def submit(request, deliveries):
    for delivery_id, message in deliveries:
        request.app.state.scheduler.submit(delivery_id, message)


def limited(request, key, maximum=20):
    consume_limit(
        request.app.state.database, [(key, maximum)], request.app.state.clock()
    )


def router():
    result = APIRouter()

    @result.get("/organisateur/contacts", name="contacts")
    def contacts(
        request: Request, identity: Annotated[Identity, Depends(current_identity)]
    ):
        if response := required_user(identity, "organizer"):
            return response
        query = request.query_params.get("q", "").strip()[:120]
        with request.app.state.database.sessions() as session:
            rows = list(
                session.scalars(select(Contact).order_by(Contact.name, Contact.id))
            )
        if query:
            rows = [
                row
                for row in rows
                if query.casefold() in (row.name + " " + row.email).casefold()
            ]
        return render(
            request, "participation/contacts.html", identity, contacts=rows, query=query
        )

    @result.post("/organisateur/contacts")
    def add_contact(
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
        form: Annotated[dict, Depends(read_selection)],
    ):
        with request.app.state.database.transaction(immediate=True) as session:
            user = checked_user(request, session, form, "organizer")
            services.add_contact(
                session,
                user.id,
                form.get("name", ""),
                form.get("email", ""),
                request.app.state.settings,
                request.app.state.clock(),
            )
        return RedirectResponse("/organisateur/contacts", status_code=303)

    @result.get(
        "/organisateur/evenements/{event_id}/invitations", name="event_invitations"
    )
    def invitations(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        with request.app.state.database.sessions() as session:
            event = authorized_event(session, event_id, identity.user.id)
            contacts = services.invitable_contacts(session)
            invitations = list(
                session.scalars(
                    select(Invitation)
                    .where(Invitation.event_id == event_id)
                    .order_by(Invitation.email)
                )
            )
            workshops = workshops_for(session, event_id)
        return render(
            request,
            "participation/invitations.html",
            identity,
            event=event,
            contacts=contacts,
            invitations=invitations,
            workshops=workshops,
            operation_id=str(uuid4()),
            now=request.app.state.clock(),
        )

    @result.post("/organisateur/evenements/{event_id}/invitations")
    def invite(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
        form: Annotated[dict, Depends(read_selection)],
    ):
        form_context(request, identity, form)
        limited(
            request, f"event-invites:{identity.user.id if identity.user else 'guest'}"
        )
        with request.app.state.database.transaction(immediate=True) as session:
            user = checked_user(request, session, form, "organizer")
            deliveries, _ = services.create_invitations(
                session,
                request.app.state.settings,
                event_id,
                user.id,
                form.get("contact_ids", []),
                form.get("workshop_ids", []),
                request.app.state.clock(),
            )
        submit(request, deliveries)
        return RedirectResponse(
            f"/organisateur/evenements/{event_id}/invitations", status_code=303
        )

    @result.post(
        "/organisateur/evenements/{event_id}/invitations/{invitation_id}/{action}"
    )
    def act(
        request: Request,
        event_id: str,
        invitation_id: str,
        action: str,
        form: Annotated[dict, Depends(read_selection)],
    ):
        with request.app.state.database.transaction(immediate=True) as session:
            user = checked_user(request, session, form, "organizer")
            deliveries = services.invitation_action(
                session,
                request.app.state.settings,
                event_id,
                user.id,
                invitation_id,
                action,
                request.app.state.clock(),
                operation_id=form.get("operation_id"),
            )
        submit(request, deliveries)
        return RedirectResponse(
            f"/organisateur/evenements/{event_id}/invitations", status_code=303
        )

    def personal_page(request, *, error=None, status=200):
        identity, token = ensure_form_identity(request)
        ensure_participation_allowed(identity.user)
        context = {
            "invitation": None,
            "error": str(error) if error else None,
            "needs_password": False,
            "must_login": False,
            "workshops": [],
            "chosen": [],
        }
        with request.app.state.database.sessions() as session:
            try:
                _, invitation, event, existing, _, must_login = (
                    services.personal_context(
                        session,
                        request.cookies.get(request.app.state.settings.cookie_name),
                        request.app.state.clock(),
                    )
                )
                chosen = list(
                    session.scalars(
                        select(InvitationWorkshop.workshop_id).where(
                            InvitationWorkshop.invitation_id == invitation.id
                        )
                    )
                )
                context.update(
                    invitation=invitation,
                    event=event,
                    needs_password=existing is None or not existing.password_hash,
                    must_login=must_login,
                    name=existing.name if existing else invitation.invitee_name or "",
                    workshops=workshops_for(session, event.id),
                    chosen=chosen,
                    places=services.places_for(session, event.id),
                )
            except AuthError as issue:
                if identity.record.pending_event_invitation_id and error is None:
                    context["error"], status = str(issue), issue.status
        return render(
            request,
            "participation/personal.html",
            identity,
            token=token,
            status=status,
            **context,
        )

    @result.get("/invitations", name="personal_invitation")
    def personal(request: Request):
        return personal_page(request)

    @result.post("/invitations/preparer")
    def prepare(request: Request, form: Annotated[dict, Depends(read_selection)]):
        limited(request, f"event-token:{request.client.host}", 30)
        with request.app.state.database.transaction(immediate=True) as session:
            identity = transaction_identity(request, session, form)
            services.prepare_personal_invitation(
                session,
                identity.record,
                form.get("token", ""),
                request.app.state.clock(),
            )
        return JSONResponse({"prepared": True})

    @result.post("/invitations")
    def respond(request: Request, form: Annotated[dict, Depends(read_selection)]):
        try:
            limited(request, f"event-response:{request.client.host}", 30)
            if form.get("action") == "decline":
                with request.app.state.database.transaction(immediate=True) as session:
                    services.decline_personal_invitation(
                        session,
                        request.cookies.get(request.app.state.settings.cookie_name),
                        form,
                        request.headers.get("origin"),
                        request.app.state.settings,
                        request.app.state.clock(),
                    )
                identity = current_identity(request)
                return render(
                    request,
                    "participation/message.html",
                    identity,
                    title="Votre refus est enregistré.",
                    message="Aucune inscription active n’a été créée.",
                )
            if form.get("action") != "accept":
                raise AuthError("Choisissez explicitement Accepter ou Refuser.", 400)
            _user, token = services.accept_personal_invitation(
                request.app.state.database,
                request.app.state.settings,
                request.cookies.get(request.app.state.settings.cookie_name),
                form,
                request.headers.get("origin"),
                request.app.state.clock(),
            )
        except (AuthError, EventError) as error:
            return personal_page(request, error=error, status=error.status)
        response = RedirectResponse("/espace", status_code=303)
        set_cookie(
            response,
            request.app.state.settings,
            token,
            request.app.state.settings.session_ttl_seconds,
        )
        return response

    @result.get("/events/{slug}/demander", name="participation_request")
    def request_page(request: Request, slug: str):
        identity, token = ensure_form_identity(request)
        ensure_participation_allowed(identity.user)
        with request.app.state.database.sessions() as session:
            event = session.scalar(
                select(Event).where(
                    Event.slug == slug,
                    Event.status == "published",
                    Event.participation_mode == "open",
                )
            )
            if event is None:
                raise EventError("Événement ouvert introuvable.", 404)
        return render(
            request, "participation/request.html", identity, token=token, event=event
        )

    @result.post("/events/{slug}/demander")
    def make_request(
        request: Request, slug: str, form: Annotated[dict, Depends(read_selection)]
    ):
        limited(request, f"public-request:{request.client.host}", 10)
        with request.app.state.database.transaction(immediate=True) as session:
            identity = transaction_identity(request, session, form)
            event = session.scalar(select(Event).where(Event.slug == slug))
            if event is None:
                raise EventError("Événement introuvable.", 404)
            deliveries = services.public_request(
                session,
                request.app.state.settings,
                event,
                identity.user,
                form.get("email", ""),
                form.get("name", ""),
                request.app.state.clock(),
            )
        submit(request, deliveries)
        return render(
            request,
            "participation/message.html",
            identity,
            title="Votre demande a été prise en compte.",
            message="Consultez votre messagerie pour vérifier votre adresse avant l’examen de la demande."
            if not identity.user
            else "L’organisateur doit approuver votre demande avant toute inscription active.",
        )

    @result.post("/organisateur/evenements/{event_id}/demandes/{user_id}/{decision}")
    def decision(
        request: Request,
        event_id: str,
        user_id: str,
        decision: str,
        form: Annotated[dict, Depends(read_selection)],
    ):
        if decision not in {"accepter", "refuser"}:
            raise EventError("Action introuvable.", 404)
        with request.app.state.database.transaction(immediate=True) as session:
            user = checked_user(request, session, form, "organizer")
            deliveries = services.decide_request(
                session,
                request.app.state.settings,
                event_id,
                user.id,
                user_id,
                decision == "accepter",
                request.app.state.clock(),
            )
        submit(request, deliveries)
        return RedirectResponse(f"/organisateur/evenements/{event_id}", status_code=303)

    def enrollment_context(session, event_id, user_id):
        event = session.get(Event, event_id)
        participation = session.get(Participation, (event_id, user_id))
        if not event or not participation or participation.status != "confirmed":
            raise EventError("Participation confirmée introuvable.", 404)
        if event.status != "published":
            raise EventError("Les inscriptions sont fermées pour cet événement.", 409)
        return event

    @result.get("/espace/evenements/{event_id}/ateliers", name="choose_workshops")
    def choices(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_participant(identity):
            return response
        with request.app.state.database.sessions() as session:
            event = enrollment_context(session, event_id, identity.user.id)
            workshops = workshops_for(session, event_id)
            places = services.places_for(session, event_id)
            chosen = list(
                session.scalars(
                    select(Enrollment.workshop_id).where(
                        Enrollment.event_id == event_id,
                        Enrollment.user_id == identity.user.id,
                        Enrollment.status == "active",
                    )
                )
            )
        return render(
            request,
            "participation/choices.html",
            identity,
            event=event,
            workshops=workshops,
            chosen=chosen,
            places=places,
        )

    @result.post("/espace/evenements/{event_id}/ateliers")
    def save_choices(
        request: Request, event_id: str, form: Annotated[dict, Depends(read_selection)]
    ):
        with request.app.state.database.transaction(immediate=True) as session:
            user = checked_participant(request, session, form)
            event = enrollment_context(session, event_id, user.id)
            selected = services.validate_enrollments(
                session, event, user.id, form.get("workshop_ids", [])
            )
            services.replace_enrollments(
                session, event, user.id, selected, request.app.state.clock()
            )
            log_action(
                session,
                event_id,
                user.id,
                "enrollments_updated",
                request.app.state.clock(),
            )
            session.flush()
            recalculate_pending(
                session,
                request.app.state.clock(),
                request.app.state.settings.batch_window_seconds,
            )
        return RedirectResponse("/espace", status_code=303)

    return result
