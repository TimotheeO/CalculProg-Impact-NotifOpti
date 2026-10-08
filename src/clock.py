"""
Horloge simulée, utilisée par les tests et les démos.

Pourquoi : le rate limiting et la fenêtre de regroupement dépendent du temps.
Tester avec de vrais `time.sleep()` rendrait les tests lents (30 secondes de
fenêtre = 30 secondes d'attente) et instables. Avec cette horloge, le temps
n'avance que quand on le décide : un test de 30 s s'exécute en quelques ms et
donne toujours le même résultat.

En production on passe simplement `time.monotonic` à la place.
"""


class SimulatedClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        """Permet d'utiliser l'objet comme une fonction : clock() -> heure actuelle."""
        return self.now

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("Le temps ne peut pas reculer")
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        """Même signature que time.sleep : ici, 'dormir' fait juste avancer l'horloge."""
        self.advance(seconds)
