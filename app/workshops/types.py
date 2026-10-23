"""Valeurs immuables partagées par validation et planification du programme."""

from dataclasses import dataclass
from datetime import datetime

FIELDS = (
    "name",
    "description",
    "location",
    "starts_at",
    "ends_at",
    "capacity",
    "status",
)


@dataclass(frozen=True)
class WorkshopData:
    name: str
    description: str
    location: str
    starts_at: datetime
    ends_at: datetime
    capacity: int | None
    status: str


def snapshot(workshop):
    return WorkshopData(**{field: getattr(workshop, field) for field in FIELDS})
