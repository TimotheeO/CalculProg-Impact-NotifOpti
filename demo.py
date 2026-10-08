"""
Démo : montre concrètement que la file de priorité fait sortir les
notifications les plus urgentes en premier, peu importe l'ordre d'ajout.

Usage :
    python3 demo_notifications.py
"""

from src.notifications import Notification, NotificationQueue, Urgency


def main():
    queue = NotificationQueue()

    # On ajoute volontairement dans le DÉSORDRE (info mineure en premier)
    # pour bien montrer que l'ORDRE D'AJOUT n'est pas l'ordre de sortie.
    to_add = [
        Notification("p5", "w4", "Nouvelle photo ajoutée à l'album", Urgency.INFO_MINEURE),
        Notification("p1", "w1", "Atelier Cuisine ANNULÉ", Urgency.ANNULATION),
        Notification("p4", "w3", "Horaire de Poterie décalé de 30min", Urgency.CHANGEMENT_HORAIRE),
        Notification("p2", "w1", "Rappel : apportez votre tablier", Urgency.INFO_MINEURE),
        Notification("p3", "w2", "Atelier Dégustation ANNULÉ", Urgency.ANNULATION),
    ]

    print("=" * 60)
    print("ORDRE D'AJOUT DANS LA FILE (volontairement mélangé) :")
    print("=" * 60)
    for n in to_add:
        print(f"  [{n.urgency.name:20}] {n.message}")
        queue.push(n)

    print()
    print("=" * 60)
    print("ORDRE RÉEL DE SORTIE (le plus urgent en premier) :")
    print("=" * 60)
    position = 1
    while not queue.is_empty():
        n = queue.pop_next()
        print(f"  {position}. [{n.urgency.name:20}] {n.message}")
        position += 1

    print()
    print("-> Les 2 ANNULATION sortent en premier (dans leur ordre d'ajout),")
    print("   puis le CHANGEMENT_HORAIRE, puis les 2 INFO_MINEURE en dernier.")


if __name__ == "__main__":
    main()