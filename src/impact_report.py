from collections.abc import Sequence

from src.graph import EventGraph
from src.impact import ImpactResult
from src.simulation import ChangeEvent


def render_impact_report(
    graph: EventGraph, events: Sequence[ChangeEvent], impacts: Sequence[ImpactResult]
) -> str:
    everyone = set(graph.participants)
    lines = []
    for event, impact in zip(events, impacts, strict=True):
        source = graph.workshops[event.workshop_id]
        lines.append(
            f"t={event.at:6.1f}s  {source.name} ({source.id}) : "
            f"{event.field} -> {event.new_value}  [{event.urgency.name}]"
        )
        for workshop_id in sorted(impact.impacted_workshop_ids):
            workshop = graph.workshops[workshop_id]
            role = "point de départ" if workshop_id == event.workshop_id else "impacté en cascade"
            lines.append(f"    atelier impacté : {workshop.name} ({workshop_id})  <- {role}")
        notified = sorted(graph.participants[p].name for p in impact.impacted_participant_ids)
        spared = sorted(graph.participants[p].name for p in everyone - impact.impacted_participant_ids)
        lines.append(
            f"    à notifier ({len(notified)}/{len(everyone)}) : {', '.join(notified) or 'personne'}"
        )
        lines.append(f"    épargnés ({len(spared)}) : {', '.join(spared) or 'personne'}")
    return "\n".join(lines)
