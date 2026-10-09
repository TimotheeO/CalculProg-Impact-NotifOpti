import argparse
import sys

from src.batching_report import render_batching_report, render_emissions
from src.data_loader import load_event_graph
from src.impact_report import render_impact_report
from src.report import render_send_histogram, render_send_order
from src.simulation import ChangeEvent, run_simulation

# Scénario : à t = 0 l'organisateur décale Cuisine ET annule Poterie, puis corrige
# Cuisine deux fois. Les deux fenêtres de 30 s se terminent ensemble : on voit donc
# à la fois la fusion, la priorité (annulations d'abord) et le débit.
DEFAULT_SCENARIO = [
    ChangeEvent(0, "w1", "horaire", "15h"),
    ChangeEvent(0, "w3", "statut", "annulé"),
    ChangeEvent(5, "w1", "horaire", "16h"),
    ChangeEvent(12, "w1", "salle", "B"),
]

EPILOG = """\
Exemples :
  python3 cli.py                                      scénario de démonstration
  python3 cli.py --list                               liste les ateliers et participants
  python3 cli.py --change 0 w1 horaire 15h            un seul changement
  python3 cli.py --change 0 w1 horaire 15h --change 5 w1 horaire 16h --limit 1

Un changement s'écrit : --change HEURE ATELIER CHAMP VALEUR
  HEURE en secondes depuis le début, ATELIER = identifiant (voir --list).

Urgence déduite automatiquement :
  champ statut + valeur annulé -> ANNULATION ; champ horaire -> CHANGEMENT_HORAIRE ;
  tout autre champ -> INFO_MINEURE.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Simule des changements d'atelier et affiche qui est notifié, comment et quand.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--change", nargs=4, action="append", metavar=("HEURE", "ATELIER", "CHAMP", "VALEUR"),
        help="un changement (répétable). Sans --change : scénario de démonstration",
    )
    parser.add_argument("--window", type=float, default=30.0,
                        help="fenêtre de regroupement en secondes (défaut : 30)")
    parser.add_argument("--limit", type=int, default=2,
                        help="nombre maximal d'envois par période (défaut : 2)")
    parser.add_argument("--period", type=float, default=1.0,
                        help="durée de la période du limiteur en secondes (défaut : 1)")
    parser.add_argument("--data", default="data/sample_event.json",
                        help="fichier JSON de l'événement (défaut : data/sample_event.json)")
    parser.add_argument("--rows", type=int, default=15,
                        help="nombre de lignes affichées pour l'ordre d'envoi (défaut : 15)")
    parser.add_argument("--list", action="store_true",
                        help="liste les ateliers et participants puis quitte")
    return parser


def fail(message: str) -> int:
    print(f"Erreur : {message}", file=sys.stderr)
    return 2


def title(text: str) -> str:
    return f"\n{'=' * 72}\n{text}\n{'=' * 72}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        graph = load_event_graph(args.data)
    except FileNotFoundError:
        return fail(f"fichier introuvable : {args.data} (lance la commande depuis la racine du projet)")

    if args.list:
        print("Ateliers :")
        for workshop in graph.workshops.values():
            print(f"  {workshop.id}  {workshop.name}  ({len(workshop.participant_ids)} inscrits)")
        print("Participants :")
        for participant in graph.participants.values():
            print(f"  {participant.id}  {participant.name}")
        return 0

    if args.change is None:
        print("Aucun --change fourni : scénario de démonstration (voir --help pour le tien).")
        events = list(DEFAULT_SCENARIO)
    else:
        events = []
        for raw_time, workshop_id, field_name, value in args.change:
            try:
                moment = float(raw_time)
            except ValueError:
                return fail(f"l'heure doit être un nombre de secondes, reçu : {raw_time}")
            if moment < 0:
                return fail(f"l'heure ne peut pas être négative, reçu : {raw_time}")
            if workshop_id not in graph.workshops:
                available = ", ".join(graph.workshops)
                return fail(f"atelier inconnu : {workshop_id}. Ateliers disponibles : {available}")
            events.append(ChangeEvent(moment, workshop_id, field_name, value))

    try:
        result = run_simulation(graph, events, args.window, args.limit, args.period)
    except ValueError as error:
        return fail(str(error))

    print(title(
        f"SIMULATION : {len(events)} changement(s), fenêtre de regroupement {args.window:g} s, "
        f"débit max {args.limit} par {args.period:g} s"
    ))

    print(title("ÉTAPE 1/4 - QUI EST IMPACTÉ ?  (parcours de graphe BFS)"))
    print(render_impact_report(graph, result.events, result.impacts))

    print(title("ÉTAPE 2/4 - FUSION DES CHANGEMENTS RAPPROCHÉS"))
    all_notifications = [n for _, batch in result.emissions for n in batch]
    print(render_batching_report(result.batcher, all_notifications))
    print("Émissions (fin de chaque fenêtre) :")
    print(render_emissions(result.emissions))

    print(title("ÉTAPE 3/4 - ORDRE D'ENVOI  (file de priorité : urgent d'abord)"))
    print(render_send_order(result.sent, max_rows=args.rows))

    print(title("ÉTAPE 4/4 - DÉBIT  (rate limiting)"))
    print(render_send_histogram(result.sent, limit=args.limit, period=args.period))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
