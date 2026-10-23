from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.auth.http import (
    Identity,
    current_identity,
    form_context,
    read_event_form,
    render,
    required_user,
    transaction_identity,
)
from app.events.services import (
    FIELDS,
    EventError,
    authorized_event,
    authorized_events,
    cancel_event,
    create_event,
    delete_draft,
    deletion_blockers,
    form_values,
    organizer_actor,
    preview_update,
    publish_event,
    revision,
    update_event,
    validate_data,
    workshops_for,
)
from app.impact import audience, schedule_conflicts
from app.models import Event, Invitation, Participation, ParticipationRequest, User


def mutation_actor(request, session, form):
    user = transaction_identity(request, session, form).user
    organizer_actor(session, user.id if user else None)
    return user.id


def event_form(
    request,
    identity,
    *,
    event=None,
    values=None,
    expected="",
    creation_id="",
    error=None,
    operation_id=None,
):
    return render(
        request,
        "events/form.html",
        identity,
        event=event,
        values=values
        or {
            field: "invitation" if field == "participation_mode" else ""
            for field in FIELDS
        },
        revision=expected,
        creation_id=creation_id,
        operation_id=operation_id or str(uuid4()),
        error=str(error) if error else None,
        errors=error.errors if error else {},
        status=error.status if error else 200,
    )


def redirect_event(request, event_id):
    return RedirectResponse(
        request.url_for("organizer_event", event_id=event_id), status_code=303
    )


def router():
    result = APIRouter()

    @result.get("/organisateur", name="organizer")
    def organizer(
        request: Request, identity: Annotated[Identity, Depends(current_identity)]
    ):
        if response := required_user(identity, "organizer"):
            return response
        with request.app.state.database.sessions() as session:
            events = list(
                session.scalars(
                    select(Event)
                    .where(authorized_events(identity.user.id))
                    .order_by(Event.starts_at, Event.id)
                )
            )
        return render(request, "events/list.html", identity, events=events)

    # La route fixe précède /{event_id} pour que « nouveau » ne soit pas un identifiant.
    @result.get("/organisateur/evenements/nouveau", name="new_event")
    def new(request: Request, identity: Annotated[Identity, Depends(current_identity)]):
        if response := required_user(identity, "organizer"):
            return response
        return event_form(request, identity, creation_id=str(uuid4()))

    @result.post("/organisateur/evenements/nouveau")
    def create(
        request: Request,
        identity: Annotated[Identity, Depends(current_identity)],
        form: Annotated[dict, Depends(read_event_form)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        form_context(request, identity, form)
        try:
            data = validate_data(form)
            with request.app.state.database.transaction(immediate=True) as session:
                actor_id = mutation_actor(request, session, form)
                event = create_event(
                    session,
                    actor_id,
                    form.get("creation_id", ""),
                    data,
                    request.app.state.clock(),
                )
        except EventError as error:
            if error.status not in {400, 422}:
                raise
            return event_form(
                request,
                identity,
                values={field: form.get(field, "") for field in FIELDS},
                creation_id=form.get("creation_id", ""),
                error=error,
            )
        return redirect_event(request, event.id)

    @result.get("/organisateur/evenements/{event_id}", name="organizer_event")
    def detail(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        with request.app.state.database.sessions() as session:
            event = authorized_event(session, event_id, identity.user.id)
            workshops = workshops_for(session, event.id)
            participants = list(
                session.execute(
                    select(Participation, User)
                    .join(User, User.id == Participation.user_id)
                    .where(Participation.event_id == event.id)
                    .order_by(User.name, User.id)
                )
            )
            invitations = list(
                session.scalars(
                    select(Invitation)
                    .where(Invitation.event_id == event.id)
                    .order_by(Invitation.email)
                )
            )
            requests = list(
                session.execute(
                    select(ParticipationRequest, User)
                    .join(User, User.id == ParticipationRequest.user_id)
                    .where(ParticipationRequest.event_id == event.id)
                    .order_by(User.name, User.id)
                )
            )
            expected = revision(event, workshops)
        return render(
            request,
            "events/detail.html",
            identity,
            event=event,
            workshops=workshops,
            participants=participants,
            invitations=invitations,
            participation_requests=requests,
            confirmed_count=sum(p.status == "confirmed" for p, _ in participants),
            revision=expected,
            now=request.app.state.clock(),
        )

    @result.get("/organisateur/evenements/{event_id}/modifier", name="edit_event")
    def edit(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        with request.app.state.database.sessions() as session:
            event = authorized_event(session, event_id, identity.user.id)
            if event.status not in {"draft", "published"}:
                raise EventError(
                    "Cet événement est annulé ou archivé et reste consultable en lecture seule.",
                    409,
                )
            expected = revision(event, workshops_for(session, event.id))
        return event_form(
            request, identity, event=event, values=form_values(event), expected=expected
        )

    @result.post("/organisateur/evenements/{event_id}/modifier")
    def update(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
        form: Annotated[dict, Depends(read_event_form)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        form_context(request, identity, form)
        with request.app.state.database.sessions() as session:
            event = authorized_event(session, event_id, identity.user.id)
        try:
            data = validate_data(form)
            if form.get("action") not in {"preview", "confirm", "revise"}:
                raise EventError(
                    "Choisissez de vérifier puis de confirmer les modifications.", 400
                )
            with request.app.state.database.transaction(immediate=True) as session:
                actor_id = mutation_actor(request, session, form)
                if form["action"] == "confirm":
                    event = update_event(
                        session,
                        event_id,
                        actor_id,
                        data,
                        form.get("revision", ""),
                        request.app.state.clock(),
                        operation_id=form.get("operation_id"),
                        window=request.app.state.settings.batch_window_seconds,
                    )
                else:
                    event, changed, planned = preview_update(
                        session, event_id, actor_id, data, form.get("revision", "")
                    )
                    impact = audience(session, event_id)
                    conflicts = schedule_conflicts(session, event_id, planned)
            if form["action"] == "revise":
                return event_form(
                    request,
                    identity,
                    event=event,
                    values={field: form.get(field, "") for field in FIELDS},
                    expected=form.get("revision", ""),
                    operation_id=form.get("operation_id"),
                )
            if form["action"] == "preview":
                return render(
                    request,
                    "events/preview.html",
                    identity,
                    event=event,
                    values={field: form.get(field, "") for field in FIELDS},
                    proposed=data,
                    changed=changed,
                    planned=planned,
                    revision=form.get("revision", ""),
                    operation_id=form.get("operation_id") or str(uuid4()),
                    impact=impact,
                    conflicts=conflicts,
                )
        except EventError as error:
            if error.status not in {400, 409, 422}:
                raise
            return event_form(
                request,
                identity,
                event=event,
                values={field: form.get(field, "") for field in FIELDS},
                expected=form.get("revision", ""),
                error=error,
                operation_id=form.get("operation_id"),
            )
        return redirect_event(request, event.id)

    @result.post("/organisateur/evenements/{event_id}/publier", name="publish_event")
    def publish(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
        form: Annotated[dict, Depends(read_event_form)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        form_context(request, identity, form)
        with request.app.state.database.transaction(immediate=True) as session:
            actor_id = mutation_actor(request, session, form)
            event = publish_event(
                session,
                event_id,
                actor_id,
                form.get("revision", ""),
                request.app.state.clock(),
            )
        return redirect_event(request, event.id)

    @result.get("/organisateur/evenements/{event_id}/supprimer", name="delete_event")
    def deletion(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        with request.app.state.database.sessions() as session:
            event = authorized_event(session, event_id, identity.user.id)
            if event.owner_id != identity.user.id:
                raise EventError(
                    "Seul le responsable principal peut supprimer ce brouillon.", 403
                )
            blockers = deletion_blockers(session, event)
            expected = revision(event, workshops_for(session, event.id))
        return render(
            request,
            "events/delete.html",
            identity,
            event=event,
            blockers=blockers,
            revision=expected,
            error=None,
            confirmation="",
        )

    @result.post("/organisateur/evenements/{event_id}/supprimer")
    def remove(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
        form: Annotated[dict, Depends(read_event_form)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        form_context(request, identity, form)
        try:
            with request.app.state.database.transaction(immediate=True) as session:
                actor_id = mutation_actor(request, session, form)
                delete_draft(
                    session,
                    event_id,
                    actor_id,
                    form.get("revision", ""),
                    form.get("confirmation", ""),
                )
        except EventError as error:
            if error.status != 422:
                raise
            with request.app.state.database.sessions() as session:
                event = authorized_event(session, event_id, identity.user.id)
            return render(
                request,
                "events/delete.html",
                identity,
                event=event,
                blockers=[],
                revision=form.get("revision", ""),
                error=str(error),
                confirmation=form.get("confirmation", ""),
                status=422,
            )
        return RedirectResponse(request.url_for("organizer"), status_code=303)

    @result.get("/organisateur/evenements/{event_id}/annuler", name="cancel_event")
    def cancellation(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        with request.app.state.database.sessions() as session:
            event = authorized_event(session, event_id, identity.user.id)
            if event.status != "published":
                raise EventError("Seul un événement publié peut être annulé.", 409)
            impact = audience(session, event_id)
            expected = revision(event, workshops_for(session, event_id))
        return render(
            request,
            "events/cancel.html",
            identity,
            event=event,
            impact=impact,
            revision=expected,
            operation_id=str(uuid4()),
            changed=["status"],
            conflicts=[],
        )

    @result.post("/organisateur/evenements/{event_id}/annuler")
    def cancellation_submit(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
        form: Annotated[dict, Depends(read_event_form)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        form_context(request, identity, form)
        with request.app.state.database.transaction(immediate=True) as session:
            actor_id = mutation_actor(request, session, form)
            event = cancel_event(
                session,
                event_id,
                actor_id,
                form.get("revision", ""),
                request.app.state.clock(),
                operation_id=form.get("operation_id"),
                window=request.app.state.settings.batch_window_seconds,
            )
        return redirect_event(request, event.id)

    return result
