from collections.abc import Sequence

from src.batching import ChangeBatcher
from src.notifications import Notification


def render_batching_report(batcher: ChangeBatcher, notifications: Sequence[Notification]) -> str:
    """Avant / après la fusion : les changements reçus, puis les notifications produites."""
    lines = [f"Changements enregistrés ({len(batcher.changes_log)}) :"]
    for change in batcher.changes_log:
        lines.append(
            f"  t={change.at:6.1f}s  {change.workshop_id}.{change.field} -> {change.new_value}"
            f"  [{change.urgency.name}]  ({change.impacted_count} personnes impactées)"
        )
    lines.append(f"Notifications émises ({len(notifications)}) :")
    for n in notifications:
        lines.append(f"  {n.participant_id:<4} [{n.urgency.name}] {n.message}")
    lines.append(
        f"Bilan : {batcher.naive_notification_count} notifications sans fusion"
        f" -> {batcher.emitted_notification_count} émises"
        f" ({batcher.notifications_saved} évitées)"
    )
    return "\n".join(lines)


def render_emissions(emissions: Sequence[tuple[float, Sequence[Notification]]]) -> str:
    """Quand les groupes fusionnés ont été émis (fin de leur fenêtre de regroupement)."""
    if not emissions:
        return "Aucune émission."
    return "\n".join(
        f"  t={moment:6.1f}s : {len(notifications)} notification(s) émise(s)"
        for moment, notifications in emissions
    )
