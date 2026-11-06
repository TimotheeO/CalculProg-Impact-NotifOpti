"""Actions personnelles et retraits organisateur, protégés dans la transaction."""

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.auth.http import (
    Identity,
    checked_participant,
    checked_user,
    current_identity,
    read_selection,
    render,
    required_participant,
    transaction_identity,
)
from app.events.services import EventError, workshops_for
from app.models import Enrollment, Event, Invitation, Participation
from app.participation import lifecycle, services


def router():
    result = APIRouter()

    @result.post("/espace/invitations/{invitation_id}/repondre")
    def invitation(
        request: Request,
        invitation_id: str,
        form: Annotated[dict, Depends(read_selection)],
    ):
        with request.app.state.database.transaction(immediate=True) as session:
            user = checked_participant(request, session, form)
            identity = transaction_identity(request, session, form)
            invitation = session.scalar(
                select(Invitation).where(
                    Invitation.id == invitation_id, Invitation.email == user.email
                )
            )
            services.check_personal_invitation(invitation, request.app.state.clock())
            identity.record.pending_event_invitation_id = invitation.id
            session.flush()
            if form.get("action") == "decline":
                services.decline_personal_invitation(
                    session,
                    request.cookies.get(request.app.state.settings.cookie_name),
                    form,
                    request.headers.get("origin"),
                    request.app.state.settings,
                    request.app.state.clock(),
                )
            elif form.get("action") != "accept":
                raise EventError("Choisissez Accepter ou Refuser.", 400)
        return RedirectResponse(
            "/espace" if form["action"] == "decline" else "/invitations",
            status_code=303,
        )

    @result.post("/espace/evenements/{event_id}/retirer")
    def leave(
        request: Request, event_id: str, form: Annotated[dict, Depends(read_selection)]
    ):
        if form.get("confirmation") != "oui":
            raise EventError("Confirmez explicitement votre désinscription.", 422)
        with request.app.state.database.transaction(immediate=True) as session:
            user = checked_participant(request, session, form)
            lifecycle.withdraw(
                session,
                event_id,
                user.id,
                user.id,
                request.app.state.clock(),
                workshop_id=form.get("workshop_id") or None,
                operation_id=form.get("operation_id"),
                window=request.app.state.settings.batch_window_seconds,
            )
        return RedirectResponse("/espace", status_code=303)

    @result.post("/organisateur/evenements/{event_id}/participants/{user_id}/retirer")
    def remove(
        request: Request,
        event_id: str,
        user_id: str,
        form: Annotated[dict, Depends(read_selection)],
    ):
        if form.get("confirmation") != "oui":
            raise EventError("Confirmez explicitement le retrait.", 422)
        with request.app.state.database.transaction(immediate=True) as session:
            actor = checked_user(request, session, form, "organizer")
            lifecycle.withdraw(
                session,
                event_id,
                user_id,
                actor.id,
                request.app.state.clock(),
                organizer=True,
                workshop_id=form.get("workshop_id") or None,
                operation_id=form.get("operation_id"),
                window=request.app.state.settings.batch_window_seconds,
            )
        return RedirectResponse(f"/organisateur/evenements/{event_id}", status_code=303)

    @result.get("/espace/evenements/{event_id}/reconfirmer")
    def reconfirm_page(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_participant(identity):
            return response
        with request.app.state.database.sessions() as session:
            participation = session.get(Participation, (event_id, identity.user.id))
            event = session.get(Event, event_id)
            if (
                not event
                or event.status != "published"
                or not participation
                or participation.status != "pending_confirmation"
            ):
                raise EventError("Participation à confirmer introuvable.", 404)
            workshops = workshops_for(session, event_id)
            places = services.places_for(session, event_id)
            chosen = list(
                session.scalars(
                    select(Enrollment.workshop_id).where(
                        Enrollment.event_id == event_id,
                        Enrollment.user_id == identity.user.id,
                        Enrollment.status == "pending_confirmation",
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
            reconfirm=True,
            places=places,
            operation_id=str(uuid4()),
        )

    @result.post("/espace/evenements/{event_id}/reconfirmer")
    def reconfirm(
        request: Request, event_id: str, form: Annotated[dict, Depends(read_selection)]
    ):
        with request.app.state.database.transaction(immediate=True) as session:
            user = checked_participant(request, session, form)
            lifecycle.confirm_participation(
                session,
                event_id,
                user.id,
                form.get("workshop_ids", []),
                request.app.state.clock(),
                request.app.state.settings.batch_window_seconds,
            )
        return RedirectResponse("/espace", status_code=303)

    return result
