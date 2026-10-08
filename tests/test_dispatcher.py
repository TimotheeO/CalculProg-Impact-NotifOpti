import pytest

from src.dispatcher import NotificationDispatcher
from src.notifications import Notification, NotificationQueue, Urgency
from src.rate_limiter import RateLimiter
from src.report import max_in_any_window, render_send_histogram, render_send_order


def build_dispatcher(clock, queue, limit, period):
    limiter = RateLimiter(max_per_period=limit, period_seconds=period, clock=clock)
    return NotificationDispatcher(queue, limiter, clock=clock, sleep=clock.sleep)


def fill_queue(count):
    """`count` notifications d'urgences mélangées : 1/10 annulations, 3/10 horaires, le reste infos."""
    queue = NotificationQueue()
    for i in range(count):
        if i % 10 == 0:
            urgency = Urgency.ANNULATION
        elif i % 10 < 4:
            urgency = Urgency.CHANGEMENT_HORAIRE
        else:
            urgency = Urgency.INFO_MINEURE
        queue.push(Notification(f"p{i}", "w1", f"message {i}", urgency))
    return queue


def test_limit_is_never_exceeded_with_120_notifications(clock):
    """Test principal de la Tâche 6 : 120 notifications, limite 5 par seconde."""
    queue = fill_queue(120)
    dispatcher = build_dispatcher(clock, queue, limit=5, period=1.0)

    sent = dispatcher.drain()

    print()
    print(render_send_histogram(sent, limit=5, period=1.0))
    assert len(sent) == 120
    assert max_in_any_window([s.sent_at for s in sent], period=1.0) <= 5


def test_urgent_notifications_leave_first_even_under_rate_limit(clock):
    queue = fill_queue(120)
    dispatcher = build_dispatcher(clock, queue, limit=5, period=1.0)

    sent = dispatcher.drain()

    print()
    print(render_send_order(sent, max_rows=14))
    urgencies = [s.notification.urgency for s in sent]
    assert urgencies == sorted(urgencies)  # jamais un moins urgent avant un plus urgent
    assert urgencies[:12] == [Urgency.ANNULATION] * 12  # les 12 annulations d'abord


def test_total_duration_matches_the_configured_rate(clock):
    """120 envois à 5/s : les 5 premiers partent à t=0, les derniers à t=23 s."""
    queue = fill_queue(120)
    dispatcher = build_dispatcher(clock, queue, limit=5, period=1.0)

    sent = dispatcher.drain()

    assert sent[0].sent_at == 0.0
    assert sent[-1].sent_at == pytest.approx(23.0)


@pytest.mark.parametrize(
    "limit, period, count",
    [(5, 1.0, 120), (10, 1.0, 150), (3, 0.5, 101), (50, 60.0, 400), (1, 2.0, 30)],
)
def test_limit_respected_for_many_configurations(clock, limit, period, count):
    queue = fill_queue(count)
    dispatcher = build_dispatcher(clock, queue, limit, period)

    sent = dispatcher.drain()

    observed = max_in_any_window([s.sent_at for s in sent], period)
    print(f"\n  limite {limit}/{period:g}s, {count} notifications -> max observé {observed}")
    assert len(sent) == count
    assert observed <= limit


def test_dispatch_available_only_sends_what_the_limiter_allows(clock):
    queue = fill_queue(20)
    dispatcher = build_dispatcher(clock, queue, limit=5, period=1.0)

    assert dispatcher.dispatch_available() == 5
    assert len(queue) == 15  # le reste attend dans la file
    assert dispatcher.dispatch_available() == 0  # rien de plus tant que le temps n'avance pas

    clock.advance(1.0)
    assert dispatcher.dispatch_available() == 5


def test_empty_queue_consumes_no_rate_limit_slot(clock):
    """Une file vide ne doit pas "brûler" de places du limiteur."""
    queue = NotificationQueue()
    limiter = RateLimiter(max_per_period=1, period_seconds=1.0, clock=clock)
    dispatcher = NotificationDispatcher(queue, limiter, clock=clock, sleep=clock.sleep)

    assert dispatcher.dispatch_available() == 0
    assert limiter.try_acquire()  # la seule place est toujours disponible


def test_send_function_is_called_for_each_notification(clock):
    queue = fill_queue(12)
    received = []
    limiter = RateLimiter(max_per_period=4, period_seconds=1.0, clock=clock)
    dispatcher = NotificationDispatcher(
        queue, limiter, send_fn=received.append, clock=clock, sleep=clock.sleep
    )

    dispatcher.drain()

    assert len(received) == 12
