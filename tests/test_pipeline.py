"""
Test d'intégration : toute la chaîne, de bout en bout.

    changement -> calcul d'impact (BFS) -> regroupement -> file de priorité
               -> limiteur de débit -> envoi
"""

from src.batching import ChangeBatcher
from src.batching_report import render_batching_report
from src.dispatcher import NotificationDispatcher
from src.notifications import NotificationQueue, Urgency
from src.rate_limiter import RateLimiter
from src.report import (
    max_in_any_window,
    render_send_histogram,
    render_send_order,
)


def test_full_pipeline_from_changes_to_rate_limited_sending(sample_graph, clock):
    batcher = ChangeBatcher(sample_graph, window_seconds=30, clock=clock)
    queue = NotificationQueue()
    limiter = RateLimiter(max_per_period=2, period_seconds=1.0, clock=clock)
    dispatcher = NotificationDispatcher(queue, limiter, clock=clock, sleep=clock.sleep)

    # L'organisateur enchaîne les modifications en moins de 30 secondes
    batcher.register_change("w1", "horaire", "15h", Urgency.CHANGEMENT_HORAIRE)
    clock.advance(5)
    batcher.register_change("w1", "horaire", "16h", Urgency.CHANGEMENT_HORAIRE)
    clock.advance(5)
    batcher.register_change("w3", "statut", "annulé", Urgency.ANNULATION)
    clock.advance(30)

    notifications = batcher.flush_ready()
    for notification in notifications:
        queue.push(notification)
    sent = dispatcher.drain()

    print()
    print(render_batching_report(batcher, notifications))
    print()
    print(render_send_order(sent))
    print()
    print(render_send_histogram(sent, limit=2, period=1.0))

    # 5 personnes impactées en tout, UNE notification chacune
    assert len(sent) == 5
    assert len({s.notification.participant_id for s in sent}) == 5
    # Les annulations (p4, p5) partent avant les changements d'horaire
    urgencies = [s.notification.urgency for s in sent]
    assert urgencies == sorted(urgencies)
    assert {s.notification.participant_id for s in sent[:2]} == {"p4", "p5"}
    # Le débit est respecté
    assert max_in_any_window([s.sent_at for s in sent], period=1.0) <= 2
