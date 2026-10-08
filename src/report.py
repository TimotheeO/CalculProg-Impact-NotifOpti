"""
Affichages texte du débit (tests visuels et démos) + vérificateur indépendant.

`max_in_any_window` est volontairement SÉPARÉ du RateLimiter : il recompte les
envois à partir de leurs horodatages, sans rien savoir du limiteur. Si le
limiteur avait un bug, ce vérificateur le détecterait. C'est ce qui donne de la
valeur au test "la limite n'est jamais dépassée".
"""

from collections import Counter
from collections.abc import Sequence

from src.dispatcher import SentNotification

_BAR = "█"


def max_in_any_window(timestamps: Sequence[float], period: float) -> int:
    """
    Nombre MAXIMAL d'envois observés sur n'importe quelle fenêtre [t, t + period).
    Deux pointeurs : O(n) après le tri.
    """
    ordered = sorted(timestamps)
    best = 0
    end = 0
    for start_index, start in enumerate(ordered):
        end = max(end, start_index)
        while end < len(ordered) and ordered[end] < start + period:
            end += 1
        best = max(best, end - start_index)
    return best


def render_send_histogram(sent: Sequence[SentNotification], limit: int, period: float) -> str:
    """Histogramme : combien de notifications envoyées par tranche de `period` secondes."""
    if not sent:
        return "(aucun envoi)"
    first = min(item.sent_at for item in sent)
    buckets = Counter(int((item.sent_at - first) // period) for item in sent)
    observed = max_in_any_window([item.sent_at for item in sent], period)
    verdict = "OK" if observed <= limit else "LIMITE DÉPASSÉE"

    lines = [f"Débit : {len(sent)} notifications, limite {limit} par {period:g}s (t = secondes depuis le 1er envoi)"]
    for bucket in range(max(buckets) + 1):
        count = buckets.get(bucket, 0)
        lines.append(f"  t={bucket * period:6.1f}s │ {_BAR * count} {count}/{limit}")
    lines.append(f"  Maximum observé sur une fenêtre : {observed} (limite {limit}) -> {verdict}")
    return "\n".join(lines)


def render_send_order(sent: Sequence[SentNotification], max_rows: int = 8) -> str:
    """Les premiers envois, avec leur heure : montre que les urgents partent d'abord."""
    lines = [f"Ordre d'envoi (les {min(max_rows, len(sent))} premiers sur {len(sent)}) :"]
    for item in list(sent)[:max_rows]:
        n = item.notification
        lines.append(f"  t={item.sent_at:6.1f}s  {n.urgency.name:<19} {n.participant_id:<4} {n.message}")
    return "\n".join(lines)
