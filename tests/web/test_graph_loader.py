import pytest

from app.models import Dependency, Enrollment, Participation, User, Workshop
from app.seeds import EVENT_ID, SECOND_EVENT_ID
from app.services import NotFound, load_graph
from src.batching import ChangeBatcher
from src.graph import EventGraph
from src.impact import compute_impacted_set
from src.notifications import Urgency


@pytest.mark.parametrize(
    "source, expected",
    [
        ("w1", {"demo-alice", "demo-sofia", "demo-mehdi", "demo-lina"}),
        ("w2", {"demo-alice", "demo-mehdi", "demo-lina"}),
        ("w3", {"demo-lina"}),
        ("w4", {"demo-nora", "demo-hugo"}),
        ("w5", {"demo-hugo"}),
        ("w6", {"demo-emma"}),
    ],
)
def test_database_graph_has_exact_unique_recipients(seeded_db, source, expected):
    with seeded_db.sessions() as session:
        result = compute_impacted_set(load_graph(session, EVENT_ID), source)
    assert result.impacted_participant_ids == expected


def test_graph_matches_existing_engine_without_database(seeded_db):
    expected = EventGraph()
    for participant, target in [("p1", "w1"), ("p2", "w2"), ("p3", "w3")]:
        expected.add_participant(participant, participant)
        expected.add_workshop(target, target)
        expected.enroll(participant, target)
    expected.add_dependency("w1", "w2")
    expected.add_dependency("w2", "w3")
    expected.add_dependency("w1", "w3")
    with seeded_db.sessions() as session:
        actual = compute_impacted_set(load_graph(session, EVENT_ID), "w1")
    assert (
        actual.impacted_workshop_ids
        == compute_impacted_set(expected, "w1").impacted_workshop_ids
    )


def test_two_events_share_a_person_without_sharing_workshops(seeded_db):
    with seeded_db.sessions() as session:
        first = load_graph(session, EVENT_ID)
        second = load_graph(session, SECOND_EVENT_ID)
    assert "demo-alex" in first.participants and "demo-alex" in second.participants
    assert "fabrique-photo" not in first.workshops
    assert "w1" not in second.workshops
    assert compute_impacted_set(second, "fabrique-photo").impacted_participant_ids == {
        "demo-alex"
    }
    assert {"demo-chloe", "demo-bruno"}.isdisjoint(first.participants)


@pytest.mark.parametrize("status", ["cancelled", "removed", "pending_confirmation"])
def test_inactive_enrollment_is_excluded(seeded_db, status):
    with seeded_db.transaction() as session:
        session.get(Enrollment, (EVENT_ID, "demo-sofia", "w1")).status = status
    with seeded_db.sessions() as session:
        assert (
            "demo-sofia"
            not in compute_impacted_set(
                load_graph(session, EVENT_ID), "w1"
            ).impacted_participant_ids
        )


@pytest.mark.parametrize("status", ["withdrawn", "removed", "pending_confirmation"])
def test_unconfirmed_participation_is_excluded_even_with_active_enrollment(
    seeded_db, status
):
    with seeded_db.transaction() as session:
        session.get(Participation, (EVENT_ID, "demo-alice")).status = status
    with seeded_db.sessions() as session:
        assert "demo-alice" not in load_graph(session, EVENT_ID).participants


def test_disabled_account_is_excluded(seeded_db):
    with seeded_db.transaction() as session:
        session.get(User, "demo-alice").is_active = False
    with seeded_db.sessions() as session:
        assert "demo-alice" not in load_graph(session, EVENT_ID).participants


def test_cancelled_workshop_and_its_links_are_excluded(seeded_db):
    with seeded_db.transaction() as session:
        session.get(Workshop, "w2").status = "cancelled"
    with seeded_db.sessions() as session:
        graph = load_graph(session, EVENT_ID)
    assert "w2" not in graph.workshops
    assert (
        "demo-mehdi" not in compute_impacted_set(graph, "w1").impacted_participant_ids
    )
    assert "w2" not in graph.get_dependent_workshops("w1")


def test_unknown_event_is_a_domain_error(seeded_db):
    with seeded_db.sessions() as session, pytest.raises(NotFound):
        load_graph(session, "missing")


def test_historic_bfs_remains_robust_to_cycles_loaded_from_database(seeded_db):
    with seeded_db.transaction() as session:
        session.add(
            Dependency(
                event_id=EVENT_ID, base_workshop_id="w3", dependent_workshop_id="w1"
            )
        )
    with seeded_db.sessions() as session:
        result = compute_impacted_set(load_graph(session, EVENT_ID), "w1")
    assert result.impacted_workshop_ids == {"w1", "w2", "w3"}
    assert len(result.impacted_participant_ids) == 4


def test_database_graph_reuses_batching_and_cancellation_rules(seeded_db, clock):
    with seeded_db.sessions() as session:
        graph = load_graph(session, EVENT_ID)
    batcher = ChangeBatcher(graph, window_seconds=60, clock=clock)
    batcher.register_change("w1", "horaire", "14h10", Urgency.CHANGEMENT_HORAIRE)
    clock.advance(50)
    batcher.register_change("w1", "horaire", "14h20", Urgency.CHANGEMENT_HORAIRE)
    clock.advance(10)
    result = batcher.flush_ready()
    assert len(result) == 4
    assert all("14h20" in n.message and "14h10" not in n.message for n in result)
    batcher.register_change("w1", "statut", "annulé", Urgency.ANNULATION)
    clock.advance(60)
    cancelled = batcher.flush_ready()
    assert len(cancelled) == 4
    assert all(
        n.urgency == Urgency.ANNULATION and "annulé" in n.message for n in cancelled
    )
