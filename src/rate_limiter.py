"""
Limiteur de débit (rate limiting) : simule la contrainte d'une vraie API
d'envoi (SMS / email / push) qui refuse d'envoyer plus de N messages par période.

Choix technique : FENÊTRE GLISSANTE ("sliding window log"), un équivalent du
token bucket mentionné dans le sujet.

    - On garde en mémoire l'heure des derniers envois (dans une deque).
    - Un nouvel envoi n'est autorisé que s'il y a moins de N envois dans la
      dernière période.

Pourquoi pas un token bucket classique ?
    Un token bucket autorise des "rafales" : un seau plein de N jetons permet
    N envois d'un coup, puis le seau se remplit en continu, donc sur une même
    seconde on peut dépasser N (rafale + recharge). La fenêtre glissante
    garantit au contraire STRICTEMENT "jamais plus de N envois sur n'importe
    quelle fenêtre de `period_seconds`", ce qui est exactement ce qu'on veut
    tester et ce que beaucoup d'API imposent.

Complexité : chaque envoi est ajouté une fois et retiré une fois de la deque
=> O(1) amorti par envoi, mémoire bornée par N.
"""

import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        max_per_period: int,
        period_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        if max_per_period <= 0:
            raise ValueError("max_per_period doit être strictement positif")
        if period_seconds <= 0:
            raise ValueError("period_seconds doit être strictement positif")
        self.max_per_period = max_per_period
        self.period_seconds = period_seconds
        self._clock = clock
        self._sent_at: deque[float] = deque()

    def _forget_expired(self, now: float) -> None:
        """Oublie les envois sortis de la fenêtre (plus vieux que la période)."""
        while self._sent_at and self._sent_at[0] + self.period_seconds <= now:
            self._sent_at.popleft()

    def try_acquire(self) -> bool:
        """
        Demande l'autorisation d'envoyer UNE notification maintenant.
        Retourne True (et mémorise l'envoi) si le débit le permet, sinon False.
        """
        now = self._clock()
        self._forget_expired(now)
        if len(self._sent_at) < self.max_per_period:
            self._sent_at.append(now)
            return True
        return False

    def seconds_until_available(self) -> float:
        """Temps à attendre avant qu'un envoi soit de nouveau possible (0 si possible maintenant)."""
        now = self._clock()
        self._forget_expired(now)
        if len(self._sent_at) < self.max_per_period:
            return 0.0
        return self._sent_at[0] + self.period_seconds - now
