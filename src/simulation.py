from dataclasses import dataclass, replace

from src.batching import CANCELLED_VALUE, STATUS_FIELD, ChangeBatcher
from src.clock import SimulatedClock
from src.dispatcher import NotificationDispatcher, SentNotification
from src.graph import EventGraph
from src.impact import ImpactResult, compute_impacted_set
from src.notifications import Notification, NotificationQueue, Urgency
from src.rate_limiter import RateLimiter


@dataclass(frozen=True)
class ChangeEvent:
    """Un changement saisi par l'organisateur, à une heure donnée (en secondes)."""

    at: float
    workshop_id: str
    field: str
    new_value: str
    urgency: Urgency | None = None  # None : déduite automatiquement (voir infer_urgency)


def infer_urgency(field: str, new_value: str) -> Urgency:
    """Déduit l'urgence d'un changement : annulation > horaire > tout le reste."""
    if field == STATUS_FIELD and new_value == CANCELLED_VALUE:
        return Urgency.ANNULATION
    if field == "horaire":
        return Urgency.CHANGEMENT_HORAIRE
    return Urgency.INFO_MINEURE


@dataclass
class SimulationResult:
    events: list[ChangeEvent]  # triés par heure, urgence résolue
    impacts: list[ImpactResult]  # un résultat BFS par changement, même ordre
    batcher: ChangeBatcher
    emissions: list[tuple[float, list[Notification]]]  # (heure d'émission, notifications)
    sent: list[SentNotification]


def run_simulation(
    graph: EventGraph,
    changes: list[ChangeEvent],
    window_seconds: float = 30.0,
    limit: int = 5,
    period_seconds: float = 1.0,
) -> SimulationResult:
    # Tri stable : deux changements à la même heure gardent l'ordre de saisie.
    # Attention : `is not None` et pas `or` : Urgency.ANNULATION vaut 0, donc "faux" en Python.
    events = [
        replace(
            change,
            urgency=(
                change.urgency
                if change.urgency is not None
                else infer_urgency(change.field, change.new_value)
            ),
        )
        for change in sorted(changes, key=lambda change: change.at)
    ]
    # Calculé d'abord : lève ValueError dès le départ si un atelier est inconnu.
    impacts = [compute_impacted_set(graph, event.workshop_id) for event in events]

    clock = SimulatedClock()
    batcher = ChangeBatcher(graph, window_seconds, clock=clock)
    queue = NotificationQueue()
    limiter = RateLimiter(limit, period_seconds, clock=clock)
    dispatcher = NotificationDispatcher(queue, limiter, clock=clock, sleep=clock.sleep)

    emissions: list[tuple[float, list[Notification]]] = []
    next_event = 0
    stalled_rounds = 0  # tours consécutifs sans aucun progrès (garde-fou anti-boucle infinie)

    while True:
        # Les prochaines heures où "quelque chose se passe"
        moments = []
        if next_event < len(events):
            moments.append(events[next_event].at)
        flush_time = batcher.next_flush_time()
        if flush_time is not None:
            moments.append(flush_time)
        if not queue.is_empty():
            moments.append(limiter.available_at())
        if not moments:
            break  # plus rien à faire : tout est envoyé

        clock.advance_to(max(min(moments), clock.now))

        # 1. Émettre les groupes dont la fenêtre est terminée
        ready = batcher.flush_ready()
        if ready:
            emissions.append((clock.now, ready))
            for notification in ready:
                queue.push(notification)

        # 2. Enregistrer les changements qui arrivent maintenant
        registered = 0
        while next_event < len(events) and events[next_event].at <= clock.now:
            event = events[next_event]
            batcher.register_change(
                event.workshop_id, event.field, event.new_value, event.urgency
            )
            next_event += 1
            registered += 1

        # 3. Envoyer tout ce que le limiteur autorise
        sent_now = dispatcher.dispatch_available()

        # Chaque tour doit faire avancer quelque chose. Sinon c'est un bug interne : on
        # préfère une erreur claire à un programme qui tourne sans fin.
        if ready or registered or sent_now:
            stalled_rounds = 0
        else:
            stalled_rounds += 1
            if stalled_rounds > 3:
                raise RuntimeError("simulation bloquée : aucun progrès (bug interne)")

    return SimulationResult(events, impacts, batcher, emissions, dispatcher.sent)
