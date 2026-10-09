import pytest

from src.notifications import Urgency
from src.report import max_in_any_window
from src.simulation import ChangeEvent, infer_urgency, run_simulation

# Rappel du jeu de données (voir conftest.py) :
#   w1 Cuisine (p1, p2) -> w2 Dégustation (p2, p3)   |   w3 Poterie (p4) -> w4 Vernissage (p5)


def simulate(graph, *changes, window=30.0, limit=5, period=1.0):
    return run_simulation(graph, list(changes), window, limit, period)


def sent_times(result):
    return [item.sent_at for item in result.sent]


@pytest.mark.parametrize("field, value, expected", [
    ("statut", "annulé", Urgency.ANNULATION),
    ("statut", "maintenu", Urgency.INFO_MINEURE),
    ("horaire", "15h", Urgency.CHANGEMENT_HORAIRE),
    ("salle", "B", Urgency.INFO_MINEURE),
])
def test_urgency_is_inferred_from_the_change(field, value, expected):
    assert infer_urgency(field, value) == expected


def test_explicit_urgency_is_respected(sample_graph):
    result = simulate(sample_graph, ChangeEvent(0, "w1", "horaire", "15h", Urgency.ANNULATION))

    assert result.events[0].urgency == Urgency.ANNULATION


def test_single_change_is_emitted_when_its_window_ends(sample_graph):
    result = simulate(sample_graph, ChangeEvent(0, "w1", "horaire", "15h"))

    assert [moment for moment, _ in result.emissions] == [30.0]
    assert len(result.sent) == 3
    assert sent_times(result) == [30.0, 30.0, 30.0]  # limite 5 : tout part d'un coup


def test_impact_is_computed_for_each_change(sample_graph):
    result = simulate(sample_graph, ChangeEvent(0, "w1", "horaire", "15h"))

    assert result.impacts[0].impacted_workshop_ids == {"w1", "w2"}
    assert result.impacts[0].impacted_participant_ids == {"p1", "p2", "p3"}


def test_close_changes_are_merged_into_one_notification_each(sample_graph):
    result = simulate(
        sample_graph,
        ChangeEvent(0, "w1", "horaire", "15h"),
        ChangeEvent(5, "w1", "horaire", "16h"),
        ChangeEvent(12, "w1", "salle", "B"),
    )

    assert result.batcher.naive_notification_count == 9
    assert len(result.sent) == 3
    assert result.batcher.notifications_saved == 6
    assert all("16h" in item.notification.message for item in result.sent)


def test_late_change_is_not_merged_with_an_expired_window(sample_graph):
    """
    Test de l'ordonnanceur : à t = 100 s, la fenêtre de 30 s du premier changement
    est terminée depuis longtemps. Les deux changements ne doivent PAS fusionner.
    """
    result = simulate(
        sample_graph,
        ChangeEvent(0, "w1", "horaire", "15h"),
        ChangeEvent(100, "w1", "horaire", "16h"),
    )

    print()
    for moment, batch in result.emissions:
        print(f"  émission à t={moment:g}s : {len(batch)} notification(s)")
    assert [moment for moment, _ in result.emissions] == [30.0, 130.0]
    alice = [item for item in result.sent if item.notification.participant_id == "p1"]
    assert len(alice) == 2  # Alice est prévenue deux fois, à deux moments distincts
    assert "15h" in alice[0].notification.message
    assert "16h" in alice[1].notification.message


def test_change_exactly_at_the_deadline_goes_to_the_next_group(sample_graph):
    result = simulate(
        sample_graph,
        ChangeEvent(0, "w1", "horaire", "15h"),
        ChangeEvent(30, "w1", "horaire", "16h"),
    )

    assert [moment for moment, _ in result.emissions] == [30.0, 60.0]


def test_rate_limit_spreads_the_sending_over_time(sample_graph):
    result = simulate(
        sample_graph,
        ChangeEvent(0, "w1", "horaire", "15h"),
        ChangeEvent(0, "w3", "horaire", "10h"),
        window=10,
        limit=1,
        period=1.0,
    )

    assert sent_times(result) == [10.0, 11.0, 12.0, 13.0, 14.0]  # 5 personnes, 1 par seconde
    assert max_in_any_window(sent_times(result), period=1.0) <= 1


def test_urgent_notifications_leave_first_when_emitted_together(sample_graph):
    result = simulate(
        sample_graph,
        ChangeEvent(0, "w1", "horaire", "15h"),
        ChangeEvent(0, "w3", "statut", "annulé"),
        window=10,
        limit=1,
    )

    first_two = result.sent[:2]
    assert {item.notification.participant_id for item in first_two} == {"p4", "p5"}
    assert all(item.notification.urgency == Urgency.ANNULATION for item in first_two)


def test_changes_are_processed_in_time_order_whatever_the_input_order(sample_graph):
    result = simulate(
        sample_graph,
        ChangeEvent(5, "w1", "horaire", "16h"),  # donné AVANT le plus ancien
        ChangeEvent(0, "w1", "horaire", "15h"),
    )

    assert [event.at for event in result.events] == [0, 5]
    assert all("16h" in item.notification.message for item in result.sent)  # le plus récent gagne


def test_unknown_workshop_is_rejected(sample_graph):
    with pytest.raises(ValueError):
        simulate(sample_graph, ChangeEvent(0, "inconnu", "horaire", "15h"))
