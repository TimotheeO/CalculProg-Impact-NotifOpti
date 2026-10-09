import pytest

from src.clock import SimulatedClock
from src.data_loader import load_event_graph


@pytest.fixture
def clock():
    """Horloge simulée neuve (t = 0) pour chaque test."""
    return SimulatedClock()


@pytest.fixture
def sample_graph():
    """
    Le jeu de données de l'événement :
      w1 Cuisine (p1, p2)  --dépendance-->  w2 Dégustation (p2, p3)
      w3 Poterie (p4)      --dépendance-->  w4 Vernissage (p5)
    """
    return load_event_graph("data/sample_event.json")
