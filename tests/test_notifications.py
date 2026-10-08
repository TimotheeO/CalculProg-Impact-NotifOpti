from src.impact import ImpactResult
from src.notifications import (
    Notification,
    NotificationQueue,
    Urgency,
    build_notifications_from_impact,
)


def test_single_push_pop():
    queue = NotificationQueue()
    n = Notification("p1", "w1", "Changement", Urgency.INFO_MINEURE)
    queue.push(n)

    assert len(queue) == 1
    assert queue.pop_next() is n
    assert queue.is_empty()


def test_most_urgent_notification_comes_out_first():
    """Exigence clé de la DoD : la plus urgente sort en premier, peu importe l'ordre d'ajout."""
    queue = NotificationQueue()
    info = Notification("p1", "w1", "info mineure", Urgency.INFO_MINEURE)
    annulation = Notification("p2", "w1", "atelier annulé", Urgency.ANNULATION)
    changement = Notification("p3", "w1", "changement d'horaire", Urgency.CHANGEMENT_HORAIRE)

    # On les ajoute volontairement dans le désordre
    queue.push(info)
    queue.push(annulation)
    queue.push(changement)

    assert queue.pop_next() is annulation
    assert queue.pop_next() is changement
    assert queue.pop_next() is info


def test_same_urgency_keeps_insertion_order():
    """Deux notifications de même urgence doivent sortir dans l'ordre d'ajout (FIFO)."""
    queue = NotificationQueue()
    first = Notification("p1", "w1", "premier", Urgency.ANNULATION)
    second = Notification("p2", "w1", "deuxième", Urgency.ANNULATION)

    queue.push(first)
    queue.push(second)

    assert queue.pop_next() is first
    assert queue.pop_next() is second


def test_pop_from_empty_queue_raises():
    queue = NotificationQueue()
    try:
        queue.pop_next()
        assert False, "devrait lever IndexError"
    except IndexError:
        pass


def test_build_notifications_from_impact():
    impact_result = ImpactResult(
        source_workshop_id="w1",
        impacted_workshop_ids={"w1", "w2"},
        impacted_participant_ids={"p1", "p2", "p3"},
    )

    notifications = build_notifications_from_impact(
        impact_result, "L'atelier Cuisine a changé de créneau", Urgency.CHANGEMENT_HORAIRE
    )

    assert len(notifications) == 3
    assert {n.participant_id for n in notifications} == {"p1", "p2", "p3"}
    assert all(n.urgency == Urgency.CHANGEMENT_HORAIRE for n in notifications)
    assert all(n.workshop_id == "w1" for n in notifications)
