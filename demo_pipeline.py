from src.batching import ChangeBatcher
from src.batching_report import render_batching_report
from src.clock import SimulatedClock
from src.data_loader import load_event_graph
from src.dispatcher import NotificationDispatcher
from src.notifications import Notification, NotificationQueue, Urgency
from src.rate_limiter import RateLimiter
from src.report import (
    render_send_histogram,
    render_send_order,
)


def title(text: str) -> None:
    print("\n" + "=" * 70)
    print(text)
    print("=" * 70)


def demo_batching_and_sending() -> None:
    title("PARTIE 1 : l'organisateur modifie plusieurs fois, chacun reçoit UN message")
    clock = SimulatedClock()
    graph = load_event_graph("data/sample_event.json")
    batcher = ChangeBatcher(graph, window_seconds=30, clock=clock)
    queue = NotificationQueue()
    limiter = RateLimiter(max_per_period=2, period_seconds=1.0, clock=clock)
    dispatcher = NotificationDispatcher(queue, limiter, clock=clock, sleep=clock.sleep)

    batcher.register_change("w1", "horaire", "15h", Urgency.CHANGEMENT_HORAIRE)
    clock.advance(5)
    batcher.register_change("w1", "horaire", "16h", Urgency.CHANGEMENT_HORAIRE)
    clock.advance(7)
    batcher.register_change("w1", "salle", "B", Urgency.INFO_MINEURE)
    clock.advance(3)
    batcher.register_change("w3", "statut", "annulé", Urgency.ANNULATION)
    clock.advance(30)  # la fenêtre de 30 s est écoulée

    notifications = batcher.flush_ready()
    for notification in notifications:
        queue.push(notification)
    sent = dispatcher.drain()

    print(render_batching_report(batcher, notifications))
    print()
    print(render_send_order(sent))
    print()
    print(render_send_histogram(sent, limit=2, period=1.0))


def demo_rate_limit_under_load() -> None:
    title("PARTIE 2 : 120 notifications d'un coup, limite de 5 par seconde")
    clock = SimulatedClock()
    queue = NotificationQueue()
    for i in range(120):
        urgency = (
            Urgency.ANNULATION if i % 10 == 0
            else Urgency.CHANGEMENT_HORAIRE if i % 10 < 4
            else Urgency.INFO_MINEURE
        )
        queue.push(Notification(f"p{i}", "w1", f"message {i}", urgency))

    limiter = RateLimiter(max_per_period=5, period_seconds=1.0, clock=clock)
    dispatcher = NotificationDispatcher(queue, limiter, clock=clock, sleep=clock.sleep)
    sent = dispatcher.drain()

    print(render_send_order(sent, max_rows=14))
    print()
    print(render_send_histogram(sent, limit=5, period=1.0))


if __name__ == "__main__":
    demo_batching_and_sending()
    demo_rate_limit_under_load()
