import time

from src.data_loader import load_event_graph
from src.graph import EventGraph
from src.impact import compute_impacted_set


def test_no_impact_when_no_dependency():
    graph = EventGraph()
    graph.add_participant("p1", "Alice")
    graph.add_workshop("w1", "Atelier Solo")
    graph.enroll("p1", "w1")

    result = compute_impacted_set(graph, "w1")

    assert result.impacted_workshop_ids == {"w1"}
    assert result.impacted_participant_ids == {"p1"}


def test_transitive_cascade_a_depends_b_depends_c():
    graph = EventGraph()
    for w in ["w1", "w2", "w3"]:
        graph.add_workshop(w, w)
    for i, p in enumerate(["p1", "p2", "p3"]):
        graph.add_participant(p, p)
        graph.enroll(p, f"w{i + 1}")

    # w2 dépend de w1, w3 dépend de w2 -> chaîne de cascade
    graph.add_dependency("w1", "w2")
    graph.add_dependency("w2", "w3")

    result = compute_impacted_set(graph, "w1")

    assert result.impacted_workshop_ids == {"w1", "w2", "w3"}
    assert result.impacted_participant_ids == {"p1", "p2", "p3"}


def test_no_duplicates_on_diamond_shaped_dependencies():
    """w1 -> w2, w1 -> w3, w2 -> w4, w3 -> w4 : w4 est atteignable par 2 chemins."""
    graph = EventGraph()
    for w in ["w1", "w2", "w3", "w4"]:
        graph.add_workshop(w, w)
    graph.add_participant("p4", "David")
    graph.enroll("p4", "w4")

    graph.add_dependency("w1", "w2")
    graph.add_dependency("w1", "w3")
    graph.add_dependency("w2", "w4")
    graph.add_dependency("w3", "w4")

    result = compute_impacted_set(graph, "w1")

    assert result.impacted_workshop_ids == {"w1", "w2", "w3", "w4"}
    # w4 ne doit apparaître qu'une fois, même si atteint par 2 chemins
    assert result.impacted_participant_ids == {"p4"}


def test_cycle_does_not_cause_infinite_loop():
    """w1 -> w2 -> w1 : cycle, l'algo doit terminer sans boucler à l'infini."""
    graph = EventGraph()
    graph.add_workshop("w1", "w1")
    graph.add_workshop("w2", "w2")
    graph.add_dependency("w1", "w2")
    graph.add_dependency("w2", "w1")

    result = compute_impacted_set(graph, "w1")

    assert result.impacted_workshop_ids == {"w1", "w2"}


def test_unknown_workshop_raises():
    graph = EventGraph()
    graph.add_workshop("w1", "w1")

    try:
        compute_impacted_set(graph, "does-not-exist")
        assert False, "devrait lever ValueError"
    except ValueError:
        pass


def test_large_graph_performance_and_correctness():
    """
    Gros graphe (perf basique) : une chaîne de 300 ateliers, chacun avec
    1 participant. Vérifie que le résultat est correct (les 300 ateliers
    et 300 participants sont bien impactés en cascade) ET que l'algorithme
    reste rapide (pas de comportement quadratique caché).
    """
    graph = EventGraph()
    n = 300
    for i in range(n):
        graph.add_workshop(f"w{i}", f"w{i}")
        graph.add_participant(f"p{i}", f"p{i}")
        graph.enroll(f"p{i}", f"w{i}")
        if i > 0:
            graph.add_dependency(f"w{i - 1}", f"w{i}")

    start = time.perf_counter()
    result = compute_impacted_set(graph, "w0")
    elapsed = time.perf_counter() - start

    assert len(result.impacted_workshop_ids) == n
    assert len(result.impacted_participant_ids) == n
    # Seuil volontairement large (test de non-régression, pas un benchmark strict)
    assert elapsed < 1.0


def test_on_sample_event_dataset():
    graph = load_event_graph("data/sample_event.json")

    result = compute_impacted_set(graph, "w1")

    # Cuisine (w1) change -> Dégustation (w2) impactée en cascade
    assert result.impacted_workshop_ids == {"w1", "w2"}
    assert result.impacted_participant_ids == {"p1", "p2", "p3"}
