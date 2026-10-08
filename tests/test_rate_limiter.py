import pytest

from src.rate_limiter import RateLimiter
from src.report import max_in_any_window


def test_allows_up_to_the_limit_then_blocks(clock):
    limiter = RateLimiter(max_per_period=3, period_seconds=1.0, clock=clock)

    results = [limiter.try_acquire() for _ in range(5)]

    assert results == [True, True, True, False, False]


def test_slots_are_freed_once_the_period_has_elapsed(clock):
    limiter = RateLimiter(max_per_period=2, period_seconds=1.0, clock=clock)
    assert limiter.try_acquire() and limiter.try_acquire()
    assert not limiter.try_acquire()

    clock.advance(0.99)
    assert not limiter.try_acquire()  # encore dans la fenêtre

    clock.advance(0.01)  # t = 1.0 : la période est écoulée
    assert limiter.try_acquire()


def test_seconds_until_available(clock):
    limiter = RateLimiter(max_per_period=1, period_seconds=2.0, clock=clock)
    assert limiter.seconds_until_available() == 0.0

    limiter.try_acquire()
    clock.advance(0.5)

    assert limiter.seconds_until_available() == pytest.approx(1.5)


def test_window_slides_instead_of_resetting(clock):
    """Fenêtre GLISSANTE : un envoi libère sa place 1 période après SON envoi, pas à un top fixe."""
    limiter = RateLimiter(max_per_period=2, period_seconds=1.0, clock=clock)
    limiter.try_acquire()  # t = 0.0
    clock.advance(0.6)
    limiter.try_acquire()  # t = 0.6
    clock.advance(0.4)  # t = 1.0 : le premier envoi sort de la fenêtre, pas le second

    assert limiter.try_acquire()  # une place libre
    assert not limiter.try_acquire()  # le second envoi (t=0.6) occupe encore la sienne


@pytest.mark.parametrize("max_per_period, period", [(0, 1.0), (-1, 1.0), (5, 0), (5, -2.0)])
def test_invalid_configuration_is_rejected(max_per_period, period):
    with pytest.raises(ValueError):
        RateLimiter(max_per_period=max_per_period, period_seconds=period)


def test_independent_checker_detects_violations():
    """
    Le vérificateur de débit doit lui-même être fiable : on lui donne un
    comportement fautif connu et il doit le voir. Sinon, le test
    "limite jamais dépassée" pourrait passer à vide.
    """
    burst = [0.0, 0.1, 0.2, 0.3]  # 4 envois en 0.3 s

    assert max_in_any_window(burst, period=1.0) == 4
    assert max_in_any_window([0.0, 1.0, 2.0], period=1.0) == 1  # bien espacés
