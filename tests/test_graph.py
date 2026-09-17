from src.data_loader import load_event_graph
from src.graph import EventGraph


def test_add_participant_and_workshop():
    graph = EventGraph()
    graph.add_participant("p1", "Alice")
    graph.add_workshop("w1", "Atelier Cuisine")

    assert "p1" in graph.participants
    assert "w1" in graph.workshops


def test_enroll_participant():
    graph = EventGraph()
    graph.add_participant("p1", "Alice")
    graph.add_workshop("w1", "Atelier Cuisine")
    graph.enroll("p1", "w1")

    assert graph.get_direct_participants("w1") == {"p1"}


def test_dependency_between_workshops():
    graph = EventGraph()
    graph.add_workshop("w1", "Atelier Cuisine")
    graph.add_workshop("w2", "Atelier Dégustation")
    graph.add_dependency("w1", "w2")

    assert graph.get_dependent_workshops("w1") == {"w2"}


def test_load_sample_event():
    graph = load_event_graph("data/sample_event.json")

    assert len(graph.participants) == 5
    assert len(graph.workshops) == 4
    # w2 dépend de w1 (changement w1 -> impacte w2 en cascade)
    assert "w2" in graph.get_dependent_workshops("w1")
    assert graph.get_direct_participants("w1") == {"p1", "p2"}
