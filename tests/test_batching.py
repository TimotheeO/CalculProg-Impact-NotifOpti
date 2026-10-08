import pytest

from src.batching import ChangeBatcher
from src.batching_report import render_batching_report
from src.notifications import Urgency

# Rappel du jeu de données (voir conftest.py) :
#   w1 Cuisine (p1, p2) -> w2 Dégustation (p2, p3)   |   w3 Poterie (p4) -> w4 Vernissage (p5)
# Un changement sur w1 impacte donc p1, p2, p3 (w2 dépend de w1).


def by_participant(notifications):
    return {n.participant_id: n for n in notifications}


def test_three_close_changes_give_one_final_coherent_notification(sample_graph, clock):
    """Test principal de la Tâche 7 : 3 changements rapprochés sur le même atelier."""
    batcher = ChangeBatcher(sample_graph, window_seconds=30, clock=clock)

    batcher.register_change("w1", "horaire", "15h", Urgency.CHANGEMENT_HORAIRE)
    clock.advance(5)
    batcher.register_change("w1", "horaire", "16h", Urgency.CHANGEMENT_HORAIRE)
    clock.advance(7)
    batcher.register_change("w1", "salle", "B", Urgency.INFO_MINEURE)

    assert batcher.flush_ready() == []  # fenêtre pas encore écoulée : on attend
    clock.advance(18)  # t = 30 s
    notifications = batcher.flush_ready()

    print()
    print(render_batching_report(batcher, notifications))
    assert len(notifications) == 3  # p1, p2, p3 : UNE seule notification chacun
    assert len(by_participant(notifications)) == 3  # aucun participant en double
    for notification in notifications:
        assert "16h" in notification.message  # la dernière valeur gagne
        assert "15h" not in notification.message  # l'ancienne valeur a disparu
        assert "salle → B" in notification.message  # les deux changements sont fusionnés
        assert notification.urgency == Urgency.CHANGEMENT_HORAIRE


def test_without_batching_there_would_be_nine_notifications(sample_graph, clock):
    batcher = ChangeBatcher(sample_graph, window_seconds=30, clock=clock)
    for value in ("15h", "16h", "17h"):
        batcher.register_change("w1", "horaire", value, Urgency.CHANGEMENT_HORAIRE)
        clock.advance(1)

    clock.advance(30)
    notifications = batcher.flush_ready()

    assert batcher.naive_notification_count == 9  # 3 changements x 3 personnes
    assert len(notifications) == 3
    assert batcher.notifications_saved == 6


def test_changes_far_apart_are_not_merged(sample_graph, clock):
    batcher = ChangeBatcher(sample_graph, window_seconds=30, clock=clock)

    batcher.register_change("w1", "horaire", "15h", Urgency.CHANGEMENT_HORAIRE)
    clock.advance(31)
    first_batch = batcher.flush_ready()
    batcher.register_change("w1", "horaire", "16h", Urgency.CHANGEMENT_HORAIRE)
    clock.advance(31)
    second_batch = batcher.flush_ready()

    assert len(first_batch) == 3 and len(second_batch) == 3
    assert "15h" in first_batch[0].message
    assert "16h" in second_batch[0].message


@pytest.mark.parametrize("window, elapsed, should_be_ready", [
    (10, 9.9, False),
    (10, 10, True),
    (60, 30, False),
    (60, 60, True),
    (0, 0, True),
])
def test_window_is_configurable(sample_graph, clock, window, elapsed, should_be_ready):
    batcher = ChangeBatcher(sample_graph, window_seconds=window, clock=clock)
    batcher.register_change("w1", "horaire", "15h", Urgency.CHANGEMENT_HORAIRE)

    clock.advance(elapsed)

    assert bool(batcher.flush_ready()) == should_be_ready


def test_cancellation_supersedes_other_changes_of_the_same_workshop(sample_graph, clock):
    batcher = ChangeBatcher(sample_graph, window_seconds=30, clock=clock)
    batcher.register_change("w3", "horaire", "15h", Urgency.CHANGEMENT_HORAIRE)
    clock.advance(10)
    batcher.register_change("w3", "statut", "annulé", Urgency.ANNULATION)

    clock.advance(30)
    notifications = batcher.flush_ready()

    print()
    print(render_batching_report(batcher, notifications))
    assert len(notifications) == 2  # p4 (Poterie) et p5 (Vernissage, dépend de Poterie)
    for notification in notifications:
        assert "annulé" in notification.message
        assert "horaire" not in notification.message  # plus d'info contradictoire
        assert notification.urgency == Urgency.ANNULATION


def test_cancellation_then_reinstatement_keeps_only_the_final_state(sample_graph, clock):
    batcher = ChangeBatcher(sample_graph, window_seconds=30, clock=clock)
    batcher.register_change("w3", "statut", "annulé", Urgency.ANNULATION)
    clock.advance(5)
    batcher.register_change("w3", "statut", "maintenu", Urgency.INFO_MINEURE)

    clock.advance(30)
    notifications = batcher.flush_ready()

    for notification in notifications:
        assert "maintenu" in notification.message
        assert "annulé" not in notification.message
        assert notification.urgency == Urgency.INFO_MINEURE


def test_participant_in_two_changed_workshops_gets_a_single_notification(sample_graph, clock):
    """p2 est inscrit à w1 ET w2 : un changement sur chacun ne doit lui donner qu'UNE notification."""
    batcher = ChangeBatcher(sample_graph, window_seconds=30, clock=clock)
    batcher.register_change("w1", "horaire", "15h", Urgency.CHANGEMENT_HORAIRE)
    batcher.register_change("w2", "salle", "C", Urgency.INFO_MINEURE)

    clock.advance(30)
    notifications = by_participant(batcher.flush_ready())

    print()
    for participant, notification in sorted(notifications.items()):
        print(f"  {participant}: {notification.message}")
    assert set(notifications) == {"p1", "p2", "p3"}
    # p1 n'est que dans w1 : il n'entend pas parler de la salle de w2
    assert "salle" not in notifications["p1"].message
    # p2 (dans w1 et w2) reçoit les deux infos dans UN seul message
    assert "horaire → 15h" in notifications["p2"].message
    assert "salle → C" in notifications["p2"].message


def test_independent_changes_do_not_interfere(sample_graph, clock):
    batcher = ChangeBatcher(sample_graph, window_seconds=30, clock=clock)
    batcher.register_change("w1", "horaire", "15h", Urgency.CHANGEMENT_HORAIRE)
    batcher.register_change("w3", "horaire", "10h", Urgency.CHANGEMENT_HORAIRE)

    clock.advance(30)
    notifications = by_participant(batcher.flush_ready())

    assert set(notifications) == {"p1", "p2", "p3", "p4", "p5"}
    assert "15h" in notifications["p1"].message and "10h" not in notifications["p1"].message
    assert "10h" in notifications["p4"].message and "15h" not in notifications["p4"].message


def test_flush_all_emits_everything_immediately(sample_graph, clock):
    batcher = ChangeBatcher(sample_graph, window_seconds=300, clock=clock)
    batcher.register_change("w1", "horaire", "15h", Urgency.CHANGEMENT_HORAIRE)

    assert batcher.flush_ready() == []
    assert len(batcher.flush_all()) == 3
    assert batcher.pending_count == 0


def test_unknown_workshop_is_rejected(sample_graph, clock):
    batcher = ChangeBatcher(sample_graph, window_seconds=30, clock=clock)

    with pytest.raises(ValueError):
        batcher.register_change("inconnu", "horaire", "15h", Urgency.CHANGEMENT_HORAIRE)


def test_negative_window_is_rejected(sample_graph):
    with pytest.raises(ValueError):
        ChangeBatcher(sample_graph, window_seconds=-1)
