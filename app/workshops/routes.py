from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.auth.http import (
    Identity,
    checked_user,
    current_identity,
    form_context,
    read_event_form,
    render,
    required_user,
)
from app.events.services import (
    PARIS,
    EventError,
    authorized_event,
    revision,
    workshops_for,
)
from app.impact import schedule_conflicts, workshop_plan_audience
from app.models import Dependency
from app.workshops.services import (
    FIELDS,
    active_enrollments,
    change_dependency,
    create_workshop,
    delete_workshop,
    preview_workshop,
    update_workshop,
    validate_workshop,
    workshop_for,
    workshop_revision,
)


def workshop_values(workshop):
    return {
        field: getattr(workshop, field).astimezone(PARIS).strftime("%Y-%m-%dT%H:%M")
        if field in {"starts_at", "ends_at"}
        else str(getattr(workshop, field))
        if getattr(workshop, field) is not None
        else ""
        for field in FIELDS
    }


def form_page(
    request,
    identity,
    event,
    *,
    workshop=None,
    values=None,
    expected="",
    creation_id="",
    operation_id=None,
    error=None,
):
    return render(
        request,
        "workshops/form.html",
        identity,
        event=event,
        workshop=workshop,
        values=values
        or {field: "active" if field == "status" else "" for field in FIELDS},
        revision=expected,
        creation_id=creation_id,
        operation_id=operation_id or str(uuid4()),
        error=str(error) if error else None,
        errors=error.errors if error else {},
        status=error.status if error else 200,
    )


def router():
    result = APIRouter()

    @result.get(
        "/organisateur/evenements/{event_id}/ateliers/nouveau", name="new_workshop"
    )
    def new(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        with request.app.state.database.sessions() as session:
            event = authorized_event(session, event_id, identity.user.id)
            if event.status not in {"draft", "published"}:
                raise EventError("Cet événement est fermé.", 409)
        return form_page(request, identity, event, creation_id=str(uuid4()))

    @result.post("/organisateur/evenements/{event_id}/ateliers/nouveau")
    def create(
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
            data = validate_workshop(form)
            with request.app.state.database.transaction(immediate=True) as session:
                user = checked_user(request, session, form, "organizer")
                workshop = create_workshop(
                    session,
                    event_id,
                    user.id,
                    form.get("creation_id", ""),
                    data,
                    request.app.state.clock(),
                )
        except EventError as error:
            return form_page(
                request,
                identity,
                event,
                values={f: form.get(f, "") for f in FIELDS},
                creation_id=form.get("creation_id", ""),
                error=error,
            )
        return RedirectResponse(
            request.url_for(
                "workshop_detail", event_id=event_id, workshop_id=workshop.id
            ),
            303,
        )

    @result.get(
        "/organisateur/evenements/{event_id}/ateliers/{workshop_id}",
        name="workshop_detail",
    )
    def detail(
        request: Request,
        event_id: str,
        workshop_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        with request.app.state.database.sessions() as session:
            event, workshop = workshop_for(
                session, event_id, workshop_id, identity.user.id
            )
            members = active_enrollments(session, workshop)
            expected = revision(event, workshops_for(session, event_id))
        return render(
            request,
            "workshops/detail.html",
            identity,
            event=event,
            workshop=workshop,
            members=members,
            revision=expected,
        )

    @result.post("/organisateur/evenements/{event_id}/ateliers/{workshop_id}/supprimer")
    def remove(
        request: Request,
        event_id: str,
        workshop_id: str,
        form: Annotated[dict, Depends(read_event_form)],
    ):
        with request.app.state.database.transaction(immediate=True) as session:
            user = checked_user(request, session, form, "organizer")
            delete_workshop(
                session,
                event_id,
                workshop_id,
                user.id,
                form.get("revision", ""),
                form.get("confirmation", ""),
                request.app.state.clock(),
            )
        return RedirectResponse(f"/organisateur/evenements/{event_id}", 303)

    @result.get(
        "/organisateur/evenements/{event_id}/ateliers/{workshop_id}/modifier",
        name="edit_workshop",
    )
    def edit(
        request: Request,
        event_id: str,
        workshop_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        with request.app.state.database.sessions() as session:
            event, workshop = workshop_for(
                session, event_id, workshop_id, identity.user.id
            )
            if event.status not in {"draft", "published"}:
                raise EventError("Cet événement est fermé.", 409)
            expected = workshop_revision(session, event)
        return form_page(
            request,
            identity,
            event,
            workshop=workshop,
            values=workshop_values(workshop),
            expected=expected,
        )

    @result.post("/organisateur/evenements/{event_id}/ateliers/{workshop_id}/modifier")
    def update(
        request: Request,
        event_id: str,
        workshop_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
        form: Annotated[dict, Depends(read_event_form)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        form_context(request, identity, form)
        with request.app.state.database.sessions() as session:
            event, workshop = workshop_for(
                session, event_id, workshop_id, identity.user.id
            )
        try:
            data = validate_workshop(form)
            if form.get("action") not in {"preview", "confirm", "revise"}:
                raise EventError("Vérifiez les modifications avant confirmation.", 400)
            with request.app.state.database.transaction(immediate=True) as session:
                user = checked_user(request, session, form, "organizer")
                if form["action"] == "confirm":
                    workshop = update_workshop(
                        session,
                        event_id,
                        workshop_id,
                        user.id,
                        data,
                        form.get("revision", ""),
                        request.app.state.clock(),
                        operation_id=form.get("operation_id"),
                        window=request.app.state.settings.batch_window_seconds,
                    )
                else:
                    event, workshop, plan = preview_workshop(
                        session,
                        event_id,
                        workshop_id,
                        user.id,
                        data,
                        form.get("revision", ""),
                    )
                    changed = next(
                        (
                            row.fields
                            for row in plan.changes
                            if row.workshop_id == workshop_id
                        ),
                        (),
                    )
                    impact = workshop_plan_audience(session, event_id, plan)
                    impact_by_field = {
                        field: workshop_plan_audience(session, event_id, plan, field)
                        for field in changed
                    }
                    by_id = {w.id: w for w in workshops_for(session, event_id)}
                    conflicts = schedule_conflicts(
                        session,
                        event_id,
                        [
                            (
                                by_id[row.workshop_id],
                                row.after.starts_at,
                                row.after.ends_at,
                            )
                            for row in plan.changes
                            if row.after.status == "active"
                            and {"starts_at", "ends_at"} & set(row.fields)
                        ],
                    )
                    spared_dependents = [by_id[key] for key in plan.spared]
            if form["action"] == "revise":
                return form_page(
                    request,
                    identity,
                    event,
                    workshop=workshop,
                    values={f: form.get(f, "") for f in FIELDS},
                    expected=form.get("revision", ""),
                    operation_id=form.get("operation_id"),
                )
            if form["action"] == "preview":
                return render(
                    request,
                    "workshops/preview.html",
                    identity,
                    event=event,
                    workshop=workshop,
                    proposed=data,
                    changed=changed,
                    values={f: form.get(f, "") for f in FIELDS},
                    revision=form.get("revision", ""),
                    operation_id=form.get("operation_id") or str(uuid4()),
                    impact=impact,
                    impact_by_field=impact_by_field,
                    cascade_plan=plan,
                    spared_dependents=spared_dependents,
                    conflicts=conflicts,
                )
        except EventError as error:
            if error.status in {403, 404}:
                raise
            return form_page(
                request,
                identity,
                event,
                workshop=workshop,
                values={f: form.get(f, "") for f in FIELDS},
                expected=form.get("revision", ""),
                operation_id=form.get("operation_id"),
                error=error,
            )
        return RedirectResponse(
            request.url_for(
                "workshop_detail", event_id=event_id, workshop_id=workshop_id
            ),
            303,
        )

    @result.get("/organisateur/evenements/{event_id}/dependances", name="dependencies")
    def dependencies(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        with request.app.state.database.sessions() as session:
            event = authorized_event(session, event_id, identity.user.id)
            workshops = workshops_for(session, event_id)
            links = list(
                session.scalars(
                    select(Dependency).where(Dependency.event_id == event_id)
                )
            )
        return render(
            request,
            "workshops/dependencies.html",
            identity,
            event=event,
            workshops=workshops,
            names={w.id: w.name for w in workshops},
            links=links,
            error=None,
        )

    @result.post("/organisateur/evenements/{event_id}/dependances")
    def dependency_submit(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
        form: Annotated[dict, Depends(read_event_form)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        form_context(request, identity, form)
        try:
            if form.get("action") not in {"add", "remove"}:
                raise EventError("Choisissez l’action d’ajout ou de retrait.", 400)
            with request.app.state.database.transaction(immediate=True) as session:
                user = checked_user(request, session, form, "organizer")
                change_dependency(
                    session,
                    event_id,
                    user.id,
                    form.get("base_id", ""),
                    form.get("dependent_id", ""),
                    form["action"] == "remove",
                    request.app.state.clock(),
                    request.app.state.settings.batch_window_seconds,
                )
        except EventError as error:
            if error.status in {403, 404}:
                raise
            with request.app.state.database.sessions() as session:
                event = authorized_event(session, event_id, identity.user.id)
                workshops = workshops_for(session, event_id)
                links = list(
                    session.scalars(
                        select(Dependency).where(Dependency.event_id == event_id)
                    )
                )
            return render(
                request,
                "workshops/dependencies.html",
                identity,
                event=event,
                workshops=workshops,
                names={w.id: w.name for w in workshops},
                links=links,
                error=str(error),
                status=error.status,
            )
        return RedirectResponse(request.url_for("dependencies", event_id=event_id), 303)

    return result
