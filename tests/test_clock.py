import pytest

from src.clock import SimulatedClock


def test_clock_starts_at_zero_and_is_callable():
    clock = SimulatedClock()

    assert clock() == 0.0


def test_advance_and_sleep_move_time_forward():
    clock = SimulatedClock()
    clock.advance(2.5)
    clock.sleep(1.5)

    assert clock() == 4.0


def test_advance_to_sets_the_exact_moment():
    clock = SimulatedClock()
    clock.advance_to(0.1 + 0.3)

    assert clock() == 0.1 + 0.3  # exactement, sans erreur d'arrondi d'addition


@pytest.mark.parametrize("action", ["advance", "advance_to"])
def test_time_cannot_go_backwards(action):
    clock = SimulatedClock(start=10)

    with pytest.raises(ValueError):
        if action == "advance":
            clock.advance(-1)
        else:
            clock.advance_to(9)
