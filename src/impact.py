"""
Calcul de l'ensemble impacté par un changement, par parcours de graphe (BFS).

C'est le cœur du sujet : à partir d'un atelier qui change (ex : créneau
déplacé), on doit trouver TOUS les ateliers impactés en cascade via les
dépendances, puis TOUS les participants concernés — sans jamais notifier
tout le monde par simplicité, et sans doublons même si le graphe contient
des cycles ou plusieurs chemins vers le même atelier.

Complexité :
    O(W + E + P) où :
    - W = nombre d'ateliers atteints par la cascade (pas le total du graphe)
    - E = nombre d'arêtes de dépendance parcourues
    - P = nombre de participants inscrits aux ateliers impactés
    Chaque atelier est visité au plus une fois grâce à `visited`, donc pas de
    re-parcours exponentiel même avec des cycles ou des chemins multiples
    (diamant : w1 -> w2, w1 -> w3, w2 -> w4, w3 -> w4). C'est linéaire dans
    la taille de la portion de graphe réellement impactée, PAS un
    brute-force O(n²) qui comparerait chaque participant à chaque atelier.

Ce module ne dépend que de `EventGraph` (Tâche 1) et sera consommé tel quel
par le futur module de notification (Tâche 5+) : `ImpactResult` expose déjà
`impacted_workshop_ids` (utile pour prioriser/grouper les notifications par
atelier) en plus de la liste finale de participants à notifier.
"""

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
