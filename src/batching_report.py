"""Affichage texte de la fusion des changements (Tâche 7) : avant / après."""

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
