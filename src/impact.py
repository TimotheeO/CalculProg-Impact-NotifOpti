from collections import deque
from dataclasses import dataclass


@dataclass
class ImpactResult:
    source_workshop_id: str
    impacted_workshop_ids: set[str]
    impacted_participant_ids: set[str]


def compute_impacted_set(graph, change_workshop_id: str) -> ImpactResult:
    """
    Calcule l'ensemble des ateliers et participants impactés par un
    changement sur `change_workshop_id`, en suivant les dépendances
    en cascade (BFS).

    Équivalent du `computeImpactedSet(changeNode)` demandé dans le sujet.
    """
    if change_workshop_id not in graph.workshops:
        raise ValueError(f"Atelier inconnu : {change_workshop_id}")

    visited: set[str] = {change_workshop_id}
    queue: deque[str] = deque([change_workshop_id])

    while queue:
        current = queue.popleft()
        for dependent_id in graph.get_dependent_workshops(current):
            if dependent_id not in visited:
                visited.add(dependent_id)
                queue.append(dependent_id)

    impacted_participants: set[str] = set()
    for workshop_id in visited:
        impacted_participants |= graph.get_direct_participants(workshop_id)

    return ImpactResult(
        source_workshop_id=change_workshop_id,
        impacted_workshop_ids=visited,
        impacted_participant_ids=impacted_participants,
    )
