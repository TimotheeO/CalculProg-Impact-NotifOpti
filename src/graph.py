"""
Modélisation du graphe de dépendances pour l'événement.

Domaine : coordination logistique d'un événement à plusieurs ateliers.

Nœuds du graphe :
- Participant (une personne)
- Workshop (un atelier / sous-groupe)

Arêtes :
- "enrolled_in" : un Participant est inscrit à un Workshop
- "depends_on"  : un Workshop dépend d'un autre Workshop
  (ex : l'atelier B ne peut pas se tenir si l'atelier A change,
  parce que les mêmes intervenants/salle sont utilisés)

Ce module fournit une structure de graphe simple, suffisante pour
implémenter ensuite un parcours BFS/DFS (Tâche 3).
"""

from dataclasses import dataclass, field


@dataclass
class Participant:
    id: str
    name: str


@dataclass
class Workshop:
    id: str
    name: str
    # IDs des participants inscrits à cet atelier
    participant_ids: set[str] = field(default_factory=set)
    # IDs des autres ateliers qui dépendent de celui-ci
    # (si CET atelier change, ceux-là sont impactés en cascade)
    dependent_workshop_ids: set[str] = field(default_factory=set)


class EventGraph:
    """Graphe représentant un événement : participants, ateliers, et leurs relations."""

    def __init__(self):
        self.participants: dict[str, Participant] = {}
        self.workshops: dict[str, Workshop] = {}

    def add_participant(self, participant_id: str, name: str) -> Participant:
        p = Participant(id=participant_id, name=name)
        self.participants[participant_id] = p
        return p

    def add_workshop(self, workshop_id: str, name: str) -> Workshop:
        w = Workshop(id=workshop_id, name=name)
        self.workshops[workshop_id] = w
        return w

    def enroll(self, participant_id: str, workshop_id: str) -> None:
        """Inscrit un participant à un atelier."""
        if participant_id not in self.participants:
            raise ValueError(f"Participant inconnu : {participant_id}")
        if workshop_id not in self.workshops:
            raise ValueError(f"Atelier inconnu : {workshop_id}")
        self.workshops[workshop_id].participant_ids.add(participant_id)

    def add_dependency(self, base_workshop_id: str, dependent_workshop_id: str) -> None:
        """
        Déclare que `dependent_workshop_id` dépend de `base_workshop_id`.

        Exemple : add_dependency("atelier_A", "atelier_B")
        => si l'atelier A change, l'atelier B (et donc ses participants)
           est impacté en cascade.
        """
        if base_workshop_id not in self.workshops:
            raise ValueError(f"Atelier inconnu : {base_workshop_id}")
        if dependent_workshop_id not in self.workshops:
            raise ValueError(f"Atelier inconnu : {dependent_workshop_id}")
        self.workshops[base_workshop_id].dependent_workshop_ids.add(dependent_workshop_id)

    def get_direct_participants(self, workshop_id: str) -> set[str]:
        """Participants directement inscrits à un atelier donné."""
        return set(self.workshops[workshop_id].participant_ids)

    def get_dependent_workshops(self, workshop_id: str) -> set[str]:
        """Ateliers qui dépendent directement de l'atelier donné."""
        return set(self.workshops[workshop_id].dependent_workshop_ids)
