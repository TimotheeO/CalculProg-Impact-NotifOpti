"""Listes autorisées, exports de tableur et clôture avec historique conservé."""

import csv
import io
from collections import Counter, defaultdict
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select

from app.auth.http import (
    Identity,
    checked_user,
    current_identity,
    read_selection,
    render,
    required_user,
)
from app.events.services import (
    EventError,
    authorized_event,
    authorized_events,
    change_event_state,
    revision,
    workshops_for,
)
from app.models import Enrollment, Event, Invitation, Participation, User


def participants_data(session, event, query):
    workshops = workshops_for(session, event.id)
    workshop_id = query.get("atelier", "")
    if workshop_id and workshop_id not in {w.id for w in workshops}:
        raise EventError("Atelier introuvable.", 404)
    enrollments = list(
        session.scalars(select(Enrollment).where(Enrollment.event_id == event.id))
    )
    people = list(
        session.execute(
            select(Participation, User)
            .join(User, User.id == Participation.user_id)
            .where(Participation.event_id == event.id)
            .order_by(User.name)
        )
    )
    invitations = list(
        session.scalars(
            select(Invitation)
            .where(Invitation.event_id == event.id)
            .order_by(Invitation.email)
        )
    )
    responses = {row.email: row.status for row in invitations}
    q, status, response = (
        query.get("q", "").strip()[:120].casefold(),
        query.get("statut", ""),
        query.get("reponse", ""),
    )
    if status and status not in {
        "confirmed",
        "withdrawn",
        "removed",
        "pending_confirmation",
    }:
        raise EventError("Statut de participation invalide.", 422)
    if response and response not in {
        "pending",
        "accepted",
        "declined",
        "revoked",
        "expired",
    }:
        raise EventError("Statut de réponse invalide.", 422)
    active_by_user = defaultdict(set)
    for enrollment in enrollments:
        if enrollment.status == "active":
            active_by_user[enrollment.user_id].add(enrollment.workshop_id)
    rows = []
    for participation, person in people:
        chosen = [w for w in workshops if w.id in active_by_user[person.id]]
        if q and q not in (person.name + " " + person.email).casefold():
            continue
        if (
            (status and participation.status != status)
            or (response and responses.get(person.email) != response)
            or (workshop_id and workshop_id not in {w.id for w in chosen})
        ):
            continue
        rows.append((participation, person, chosen))
    invitations = [
        i
        for i in invitations
        if (not q or q in ((i.invitee_name or "") + " " + i.email).casefold())
        and (not response or i.status == response)
    ]
    return {
        "people": rows,
        "invitations": invitations,
        "workshops": workshops,
        "enrollments": enrollments,
        "response_counts": Counter(responses.values()),
    }


def spreadsheet_cell(value):
    value = "" if value is None else str(value)
    return (
        "'" + value
        if value.lstrip().startswith(("=", "+", "-", "@"))
        or value.startswith(("\t", "\r", "\n"))
        else value
    )


def csv_content(session, event, kind, data):
    rows = []
    if kind == "participants":
        header = ["Nom", "E-mail", "Participation", "Ateliers actifs"]
        rows = [
            [u.name, u.email, p.status, " ; ".join(w.name for w in workshops)]
            for p, u, workshops in data["people"]
        ]
    elif kind == "inscriptions":
        header = ["Nom", "E-mail", "Atelier", "État", "Début Paris", "Fin Paris"]
        allowed = {u.id: u for _, u, _ in data["people"]}
        workshops = {w.id: w for w in data["workshops"]}
        from app.events.services import PARIS

        for enrollment in data["enrollments"]:
            if enrollment.user_id in allowed:
                user, workshop = (
                    allowed[enrollment.user_id],
                    workshops[enrollment.workshop_id],
                )
                rows.append(
                    [
                        user.name,
                        user.email,
                        workshop.name,
                        enrollment.status,
                        workshop.starts_at.astimezone(PARIS).isoformat(),
                        workshop.ends_at.astimezone(PARIS).isoformat(),
                    ]
                )
    elif kind == "reponses":
        header = ["Nom", "E-mail", "Réponse", "Type", "Expiration UTC"]
        rows = [
            [i.invitee_name, i.email, i.status, i.purpose, i.expires_at.isoformat()]
            for i in data["invitations"]
        ]
    else:
        raise EventError("Type d’export inconnu.", 422)
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(header)
    writer.writerows([[spreadsheet_cell(cell) for cell in row] for row in rows])
    return "\ufeff" + output.getvalue()


def router():
    result = APIRouter()

    @result.get("/organisateur/evenements/{event_id}/participants")
    def people(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        with request.app.state.database.sessions() as session:
            event = authorized_event(session, event_id, identity.user.id)
            data = participants_data(session, event, request.query_params)
            events = list(
                session.scalars(
                    select(Event)
                    .where(authorized_events(identity.user.id))
                    .order_by(Event.starts_at)
                )
            )
        return render(
            request,
            "events/participants.html",
            identity,
            event=event,
            events=events,
            query=request.query_params,
            **data,
        )

    @result.get("/organisateur/evenements/{event_id}/export.csv")
    def export(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        kind = request.query_params.get("type", "participants")
        with request.app.state.database.sessions() as session:
            event = authorized_event(session, event_id, identity.user.id)
            data = participants_data(session, event, request.query_params)
            body = csv_content(session, event, kind, data)
        return Response(
            body,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="impactflow-{kind}.csv"',
                "Cache-Control": "no-store",
            },
        )

    @result.get("/organisateur/evenements/{event_id}/etat/{action}")
    def state_page(
        request: Request,
        event_id: str,
        action: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        if action not in {"archiver", "reactiver"}:
            raise EventError("Action introuvable.", 404)
        with request.app.state.database.sessions() as session:
            event = authorized_event(session, event_id, identity.user.id)
            expected = revision(event, workshops_for(session, event_id))
        return render(
            request,
            "events/state.html",
            identity,
            event=event,
            action=action,
            revision=expected,
            operation_id=str(uuid4()),
        )

    @result.post("/organisateur/evenements/{event_id}/etat/{action}")
    def change_state(
        request: Request,
        event_id: str,
        action: str,
        form: Annotated[dict, Depends(read_selection)],
    ):
        with request.app.state.database.transaction(immediate=True) as session:
            user = checked_user(request, session, form, "organizer")
            event = authorized_event(session, event_id, user.id)
            if form.get("confirmation", "").strip() != event.name:
                raise EventError(
                    "Recopiez le nom exact de l’événement pour confirmer.", 422
                )
            change_event_state(
                session,
                event_id,
                user.id,
                action,
                form.get("revision", ""),
                request.app.state.clock(),
                operation_id=form.get("operation_id"),
                window=request.app.state.settings.batch_window_seconds,
            )
        return RedirectResponse(f"/organisateur/evenements/{event_id}", status_code=303)

    return result
