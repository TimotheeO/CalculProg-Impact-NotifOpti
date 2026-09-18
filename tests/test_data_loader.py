from src.data_loader import load_event_graph


def test_load_sample_event():
    graph = load_event_graph("data/sample_event.json")

    assert len(graph.participants) == 5
    assert len(graph.workshops) == 4
    # w2 dépend de w1 (changement w1 -> impacte w2 en cascade)
    assert "w2" in graph.get_dependent_workshops("w1")
    assert graph.get_direct_participants("w1") == {"p1", "p2"}


def test_load_sample_event_dependencies_are_preserved():
    graph = load_event_graph("data/sample_event.json")

    # w4 dépend de w3 (autre chaîne de cascade indépendante)
    assert "w4" in graph.get_dependent_workshops("w3")
