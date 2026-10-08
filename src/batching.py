"""
Regroupement (batching / debouncing) des changements rapprochés.

Problème : si l'organisateur change 3 fois l'horaire d'un atelier en 2 minutes,
chaque participant ne doit PAS recevoir 3 notifications (dont 2 déjà fausses),
mais UNE seule, cohérente, qui reflète l'état final.

Fonctionnement :
    1. `register_change` calcule les personnes impactées (BFS de la Tâche 3) et
       les met "en attente" dans un groupe, UN groupe par participant.
    2. Tant que la fenêtre de regroupement n'est pas écoulée, les nouveaux
       changements qui touchent le même participant sont FUSIONNÉS dans son
       groupe (détection des redondances : même participant = même groupe).
    3. `flush_ready` produit une seule `Notification` par groupe dont la fenêtre
       est écoulée.

Règles de fusion (ce qui rend la notification "cohérente") :
    - Même atelier + même champ modifié plusieurs fois : la DERNIÈRE valeur gagne
      (horaire 15h puis 16h => on n'annonce que 16h).
    - Un atelier annulé : l'annulation rend caduques ses autres changements
      (inutile d'annoncer "horaire décalé" pour un atelier qui n'a plus lieu).
    - L'urgence finale est la plus haute parmi les changements restants.

Politique de fenêtre : fixe, démarrée au PREMIER changement du groupe (batching).
Alternative "debounce pur" (fenêtre relancée à chaque changement) : plus de
fusion, mais une notification qui pourrait être retardée indéfiniment si les
changements ne s'arrêtent jamais. La fenêtre fixe borne le délai maximal.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from src.graph import EventGraph
from src.impact import compute_impacted_set
from src.notifications import Notification, Urgency

STATUS_FIELD = "statut"
CANCELLED_VALUE = "annulé"


@dataclass(frozen=True)
class RegisteredChange:
    """Trace d'un changement enregistré (sert au journal et aux affichages)."""

    at: float
    workshop_id: str
    field: str
    new_value: str
    urgency: Urgency
    impacted_count: int


@dataclass
class _PendingGroup:
    """Changements en attente pour UN participant."""

    opened_at: float
    # (atelier, champ) -> (dernière valeur, urgence). Réécrire une clé existante
    # écrase l'ancienne valeur : c'est ce qui implémente "la dernière valeur gagne".
    changes: dict[tuple[str, str], tuple[str, Urgency]] = field(default_factory=dict)


class ChangeBatcher:
    def __init__(
        self,
        graph: EventGraph,
        window_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        if window_seconds < 0:
            raise ValueError("window_seconds ne peut pas être négatif")
        self._graph = graph
        self._window = window_seconds
        self._clock = clock
        self._pending: dict[str, _PendingGroup] = {}
        self.changes_log: list[RegisteredChange] = []
        self.naive_notification_count = 0  # ce qu'on aurait envoyé SANS fusion
        self.emitted_notification_count = 0  # ce qu'on a réellement produit

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def notifications_saved(self) -> int:
        """Notifications évitées grâce à la fusion."""
        return self.naive_notification_count - self.emitted_notification_count

    def register_change(
        self, workshop_id: str, field_name: str, new_value: str, urgency: Urgency
    ) -> int:
        """Enregistre un changement. Retourne le nombre de participants impactés."""
        impact = compute_impacted_set(self._graph, workshop_id)
        now = self._clock()

        for participant_id in impact.impacted_participant_ids:
            group = self._pending.get(participant_id)
            if group is None:
                group = _PendingGroup(opened_at=now)
                self._pending[participant_id] = group
            group.changes[(workshop_id, field_name)] = (new_value, urgency)

        impacted_count = len(impact.impacted_participant_ids)
        self.naive_notification_count += impacted_count
        self.changes_log.append(
            RegisteredChange(now, workshop_id, field_name, new_value, urgency, impacted_count)
        )
        return impacted_count

    def flush_ready(self) -> list[Notification]:
        """Produit les notifications des groupes dont la fenêtre est écoulée."""
        now = self._clock()
        ready_ids = [
            participant_id
            for participant_id, group in self._pending.items()
            if now - group.opened_at >= self._window
        ]
        return self._flush(ready_ids)

    def flush_all(self) -> list[Notification]:
        """Force l'émission de tous les groupes, même si leur fenêtre n'est pas écoulée."""
        return self._flush(list(self._pending))

    def _flush(self, participant_ids: list[str]) -> list[Notification]:
        notifications = [
            self._build_notification(participant_id, self._pending.pop(participant_id))
            for participant_id in participant_ids
        ]
        self.emitted_notification_count += len(notifications)
        return notifications

    def _build_notification(self, participant_id: str, group: _PendingGroup) -> Notification:
        # 1. Un atelier annulé rend caduques ses autres changements.
        cancelled = {
            workshop
            for (workshop, field_name), (value, _) in group.changes.items()
            if field_name == STATUS_FIELD and value == CANCELLED_VALUE
        }
        effective = {
            key: value
            for key, value in group.changes.items()
            if key[0] not in cancelled or key[1] == STATUS_FIELD
        }

        # 2. L'urgence finale est la plus haute (la valeur la plus basse de l'enum).
        urgency = min(urgency for _, urgency in effective.values())

        # 3. Un seul message : "Atelier A : horaire → 16h, salle → B | Atelier B : annulé"
        parts_by_workshop: dict[str, list[str]] = {}
        for (workshop, field_name), (value, _) in effective.items():
            text = value if field_name == STATUS_FIELD else f"{field_name} → {value}"
            parts_by_workshop.setdefault(workshop, []).append(text)
        message = " | ".join(
            f"{self._graph.workshops[workshop].name} : {', '.join(parts)}"
            for workshop, parts in parts_by_workshop.items()
        )

        main_workshop = next(iter(parts_by_workshop))
        return Notification(participant_id, main_workshop, message, urgency)
