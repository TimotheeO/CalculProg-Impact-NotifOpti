"""Conséquences concrètes : BFS de candidats puis ordonnancement topologique."""

from dataclasses import dataclass, replace
from graphlib import CycleError, TopologicalSorter

from app.events.services import EventError
from app.workshops.types import FIELDS, WorkshopData, snapshot
from src.graph import EventGraph
from src.impact import compute_impacted_set


@dataclass(frozen=True)
class PlannedWorkshop:
    workshop_id: str
    before: WorkshopData
    after: WorkshopData
    fields: tuple[str, ...]
    automatic: bool = False
    reason: str = ""


@dataclass(frozen=True)
class WorkshopPlan:
    source_id: str
    changes: tuple[PlannedWorkshop, ...]
    spared: tuple[str, ...]


def plan_change(
    workshops, dependencies, source_id, proposed, *, reactivate_dependents=False
):
    """Ne modifie aucun objet ORM. Une branche qui absorbe le retard s’arrête."""
    current = {w.id: snapshot(w) for w in workshops}
    if source_id not in current:
        raise EventError("Atelier introuvable dans cet événement.", 404)
    source = current[source_id]
    fields = tuple(
        field for field in FIELDS if getattr(source, field) != getattr(proposed, field)
    )
    if not fields:
        return WorkshopPlan(source_id, (), ())
    root = PlannedWorkshop(source_id, source, proposed, fields)
    if source.status == "cancelled" and proposed.status == "active":
        parents = {key: set() for key in current}
        graph = EventGraph()
        for key, value in current.items():
            graph.add_workshop(key, value.name)
        for edge in dependencies:
            graph.add_dependency(edge.base_workshop_id, edge.dependent_workshop_id)
            parents[edge.dependent_workshop_id].add(edge.base_workshop_id)
        selected = (
            compute_impacted_set(graph, source_id).impacted_workshop_ids
            if reactivate_dependents
            else {source_id}
        )
        try:
            order = TopologicalSorter(
                {key: parents[key] & selected for key in selected}
            ).static_order()
            final, changes = dict(current), []
            for key in order:
                before = current[key]
                if key != source_id and before.status == "active":
                    continue
                after = (
                    proposed if key == source_id else replace(before, status="active")
                )
                if any(final[parent].status != "active" for parent in parents[key]):
                    raise EventError(
                        "Réactivez d’abord tous les prérequis de cet atelier.", 409
                    )
                required = max(
                    (final[parent].ends_at for parent in parents[key]),
                    default=after.starts_at,
                )
                if key == source_id and after.starts_at < required:
                    raise EventError(
                        "L’atelier réactivé doit commencer après ses prérequis.", 409
                    )
                if after.starts_at < required:
                    after = replace(
                        after,
                        starts_at=required,
                        ends_at=required + (after.ends_at - after.starts_at),
                    )
                final[key] = after
                changes.append(
                    PlannedWorkshop(
                        key,
                        before,
                        after,
                        tuple(
                            f for f in FIELDS if getattr(before, f) != getattr(after, f)
                        ),
                        key != source_id,
                        "Réactivation proposée ; nouvelle confirmation des inscrits nécessaire.",
                    )
                )
            return WorkshopPlan(source_id, tuple(changes), ())
        except CycleError as error:
            raise EventError(
                "Une boucle empêche la réactivation. Corrigez les dépendances.", 409
            ) from error
    cancelling = "status" in fields and proposed.status == "cancelled"
    scheduling = proposed.status == "active" and bool(
        {"starts_at", "ends_at"} & set(fields)
    )
    if not cancelling and not scheduling:
        return WorkshopPlan(source_id, (root,), ())
    graph = EventGraph()
    for key, value in current.items():
        if cancelling or value.status == "active" or key == source_id:
            graph.add_workshop(key, value.name)
    parents = {key: set() for key in graph.workshops}
    for dependency in dependencies:
        parent, child = dependency.base_workshop_id, dependency.dependent_workshop_id
        if parent in graph.workshops and child in graph.workshops:
            graph.add_dependency(parent, child)
            parents[child].add(parent)
    candidates = compute_impacted_set(graph, source_id).impacted_workshop_ids
    try:
        order = tuple(
            TopologicalSorter(
                {key: parents[key] & candidates for key in sorted(candidates)}
            ).static_order()
        )
    except CycleError as error:
        raise EventError(
            "Une boucle empêche la planification. Corrigez les dépendances avant de modifier le programme.",
            409,
        ) from error
    if scheduling:
        required = [
            current[key].ends_at
            for key in parents[source_id]
            if current[key].status == "active"
        ]
        if required and proposed.starts_at < max(required):
            raise EventError(
                "Cet atelier doit commencer après la fin de tous ses prérequis.",
                errors={"starts_at": "Le début précède la fin d’un atelier requis."},
            )
    final = {**current, source_id: proposed}
    moved = {source_id}
    changes = [root]
    for key in order:
        if key == source_id:
            continue
        before = current[key]
        if cancelling:
            if before.status == "cancelled":
                continue
            after = replace(before, status="cancelled")
            reason = f"Annulation en cascade après « {proposed.name} »."
        else:
            if not (parents[key] & moved):
                continue
            required_end = max(final[parent].ends_at for parent in parents[key])
            if before.starts_at >= required_end:
                continue
            delay = required_end - before.starts_at
            try:
                after = replace(
                    before, starts_at=required_end, ends_at=before.ends_at + delay
                )
            except OverflowError as error:
                raise EventError(
                    "Le décalage calculé dépasse les dates autorisées."
                ) from error
            reason = f"Décalage nécessaire après « {proposed.name} » ; durée conservée."
        final[key] = after
        moved.add(key)
        changes.append(
            PlannedWorkshop(
                key,
                before,
                after,
                tuple(
                    field
                    for field in FIELDS
                    if getattr(before, field) != getattr(after, field)
                ),
                automatic=True,
                reason=reason,
            )
        )
    return WorkshopPlan(source_id, tuple(changes), tuple(sorted(candidates - moved)))
