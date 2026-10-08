import heapq
import itertools
from dataclasses import dataclass
from enum import IntEnum


class Urgency(IntEnum):
    ANNULATION = 0
    CHANGEMENT_HORAIRE = 1
    INFO_MINEURE = 2


@dataclass
class Notification:
    participant_id: str
    workshop_id: str
    message: str
    urgency: Urgency


class NotificationQueue:

    def __init__(self):
        self._heap: list[tuple[Urgency, int, Notification]] = []
        self._counter = itertools.count()

    def push(self, notification: Notification) -> None:
        count = next(self._counter)
        heapq.heappush(self._heap, (notification.urgency, count, notification))

    def pop_next(self) -> Notification:
        if not self._heap:
            raise IndexError("La file de notification est vide")
        _, _, notification = heapq.heappop(self._heap)
        return notification

    def is_empty(self) -> bool:
        return len(self._heap) == 0

    def __len__(self) -> int:
        return len(self._heap)


def build_notifications_from_impact(impact_result, message: str, urgency: Urgency) -> list[Notification]:
    return [
        Notification(
            participant_id=participant_id,
            workshop_id=impact_result.source_workshop_id,
            message=message,
            urgency=urgency,
        )
        for participant_id in impact_result.impacted_participant_ids
    ]
