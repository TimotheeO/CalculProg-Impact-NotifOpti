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

    def advance_to(self, moment: float) -> None:
        """Place l'horloge EXACTEMENT à `moment` (évite les erreurs d'arrondi d'une addition)."""
        if moment < self.now:
            raise ValueError("Le temps ne peut pas reculer")
        self.now = moment

    def sleep(self, seconds: float) -> None:
        """Même signature que time.sleep : ici, 'dormir' fait juste avancer l'horloge."""
        self.advance(seconds)
