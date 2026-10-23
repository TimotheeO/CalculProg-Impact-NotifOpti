"""Commandes idempotentes et journal métier, sans dépendance au transport HTTP."""

import hashlib
import json
from uuid import UUID, uuid4

from app.events.services import EventError
from app.models import EventAction, EventOperation


def begin_operation(session, event_id, actor_id, kind, payload, now, operation_id=None):
    try:
        operation_id = str(UUID(operation_id)) if operation_id else str(uuid4())
    except (ValueError, TypeError, AttributeError) as error:
        raise EventError(
            "Le formulaire n’est plus valide. Rechargez la page.", 400
        ) from error
    encoded = json.dumps(
        payload,
        sort_keys=True,
        default=lambda value: value.isoformat(),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    previous = session.get(EventOperation, operation_id)
    if previous:
        if (
            previous.event_id,
            previous.actor_id,
            previous.kind,
            previous.request_digest,
        ) != (event_id, actor_id, kind, digest):
            raise EventError(
                "Cette confirmation a déjà été utilisée pour une autre action. Rechargez le formulaire.",
                409,
            )
        return previous, False
    operation = EventOperation(
        id=operation_id,
        event_id=event_id,
        actor_id=actor_id,
        kind=kind,
        request_digest=digest,
        created_at=now,
    )
    session.add(operation)
    session.flush()
    return operation, True


def log_action(session, event_id, actor_id, kind, now, *, target_id=None, detail=None):
    session.add(
        EventAction(
            id=str(uuid4()),
            event_id=event_id,
            actor_id=actor_id,
            kind=kind,
            target_id=target_id,
            detail=detail or {},
            created_at=now,
        )
    )
