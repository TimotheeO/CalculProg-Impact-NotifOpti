"""Graphe consultable et compteurs calculés depuis les données autorisées."""

from collections import Counter, defaultdict
from graphlib import CycleError, TopologicalSorter
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from app.auth.http import Identity, current_identity, render, required_user
from app.events.services import EventError, authorized_event, workshops_for
from app.journal import snapshot
from app.models import (
    Dependency,
    Enrollment,
    Invitation,
    MailAttempt,
    MailDelivery,
    Participation,
    ParticipationRequest,
    User,
)


def graph_data(session, event_id, *, source_id=None, changed_ids=None):
    workshops = workshops_for(session, event_id)
    parents = {w.id: set() for w in workshops}
    edges = list(
        session.scalars(select(Dependency).where(Dependency.event_id == event_id))
    )
    for edge in edges:
        parents[edge.dependent_workshop_id].add(edge.base_workshop_id)
    try:
        order = tuple(TopologicalSorter(parents).static_order())
    except CycleError as error:
        raise EventError(
            "Le graphe contient une boucle. Corrigez les dépendances.", 409
        ) from error
    levels, columns = {}, defaultdict(list)
    for key in order:
        levels[key] = max((levels[p] + 1 for p in parents[key]), default=0)
        columns[levels[key]].append(key)
    positions = {
        key: (35 + level * 260, 30 + index * 100)
        for level, keys in columns.items()
        for index, key in enumerate(keys)
    }
    return {
        "source": source_id,
        "changed": list(changed_ids or []),
        "preview": changed_ids is not None,
        "nodes": [
            {
                "id": w.id,
                "name": w.name,
                "status": w.status,
                "x": positions[w.id][0],
                "y": positions[w.id][1],
            }
            for w in workshops
        ],
        "edges": [
            {
                "from": e.base_workshop_id,
                "to": e.dependent_workshop_id,
                "x1": positions[e.base_workshop_id][0] + 220,
                "y1": positions[e.base_workshop_id][1] + 30,
                "x2": positions[e.dependent_workshop_id][0],
                "y2": positions[e.dependent_workshop_id][1] + 30,
            }
            for e in edges
        ],
        "width": max(360, len(columns) * 260 + 30),
        "height": max(
            140, max((len(c) for c in columns.values()), default=1) * 100 + 30
        ),
    }


def counters(session, event_id, now):
    invitations = list(
        session.scalars(
            select(Invitation).where(
                Invitation.event_id == event_id, Invitation.purpose == "invitation"
            )
        )
    )
    requests = Counter(
        session.scalars(
            select(ParticipationRequest.status).where(
                ParticipationRequest.event_id == event_id
            )
        )
    )
    responses = Counter(
        "expired" if i.status == "pending" and i.expires_at <= now else i.status
        for i in invitations
    )
    participants = list(
        session.scalars(
            select(Participation)
            .join(User, User.id == Participation.user_id)
            .where(
                Participation.event_id == event_id,
                User.is_active.is_(True),
                User.role != "super_admin",
            )
        )
    )
    enrollments = list(
        session.scalars(select(Enrollment).where(Enrollment.event_id == event_id))
    )
    rows, mail, stats = snapshot(session, event_id=event_id)
    attempts = list(
        session.scalars(
            select(MailAttempt)
            .join(MailDelivery, MailDelivery.id == MailAttempt.delivery_id)
            .where(MailDelivery.event_id == event_id)
        )
    )
    confirmed_ids = {p.user_id for p in participants if p.status == "confirmed"}
    active_workshops = {
        w.id for w in workshops_for(session, event_id) if w.status == "active"
    }
    return {
        **stats,
        "confirmed": sum(p.status == "confirmed" for p in participants),
        "enrollments": sum(
            e.status == "active"
            and e.user_id in confirmed_ids
            and e.workshop_id in active_workshops
            for e in enrollments
        ),
        "responses": responses,
        "requests": requests,
        "queue": sum(n.status in {"pending", "ready"} for n in rows),
        "accepted": sum(m.status in {"accepted", "simulated"} for m in mail),
        "failed": sum(m.status == "failed" for m in mail),
        "uncertain": sum(m.status == "uncertain" for m in mail),
        "retries": sum(a.actor_id is not None for a in attempts),
    }


def router():
    result = APIRouter()

    @result.get("/organisateur/evenements/{event_id}/tableau-de-bord")
    def dashboard(
        request: Request,
        event_id: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ):
        if response := required_user(identity, "organizer"):
            return response
        with request.app.state.database.sessions() as session:
            event = authorized_event(session, event_id, identity.user.id)
            graph = graph_data(session, event_id)
            stats = counters(session, event_id, request.app.state.clock())
        return render(
            request,
            "dashboard.html",
            identity,
            event=event,
            graph=graph,
            dashboard=stats,
        )

    return result
