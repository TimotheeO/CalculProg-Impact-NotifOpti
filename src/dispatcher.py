"""
Dispatcher : relie la file de priorité (Tâche 5) et le limiteur de débit (Tâche 6).

Règle : on envoie TOUJOURS la notification la plus urgente en premier, mais
seulement quand le limiteur de débit l'autorise. Si le débit est atteint, on
attend (sleep) le temps nécessaire, puis on reprend.

L'envoi réel (SMS / email / push) est simulé : `send_fn` est une fonction
qu'on peut remplacer par un vrai appel d'API sans toucher au reste du code.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

from src.notifications import Notification, NotificationQueue
from src.rate_limiter import RateLimiter

# Attente minimale quand le limiteur n'est pas prêt : évite une boucle infinie
# si une erreur d'arrondi de flottants donnait une attente de 0.000...01 s.
_MIN_WAIT_SECONDS = 1e-6


@dataclass(frozen=True)
class SentNotification:
    notification: Notification
    sent_at: float


class NotificationDispatcher:
    def __init__(
        self,
        queue: NotificationQueue,
        limiter: RateLimiter,
        send_fn: Callable[[Notification], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._queue = queue
        self._limiter = limiter
        self._send_fn = send_fn or (lambda notification: None)
        self._clock = clock
        self._sleep = sleep
        self.sent: list[SentNotification] = []

    def dispatch_available(self) -> int:
        """Envoie tout ce que le limiteur autorise MAINTENANT. Retourne le nombre envoyé."""
        count = 0
        # Ordre des conditions important : on ne consomme un "slot" du limiteur
        # que s'il reste réellement une notification à envoyer.
        while not self._queue.is_empty() and self._limiter.try_acquire():
            notification = self._queue.pop_next()
            self._send_fn(notification)
            self.sent.append(SentNotification(notification, self._clock()))
            count += 1
        return count

    def drain(self) -> list[SentNotification]:
        """Envoie TOUTE la file en respectant le débit (attend quand c'est nécessaire)."""
        while not self._queue.is_empty():
            self.dispatch_available()
            if not self._queue.is_empty():
                wait = max(self._limiter.seconds_until_available(), _MIN_WAIT_SECONDS)
                self._sleep(wait)
        return self.sent
