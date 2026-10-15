import argparse
import json
import sys

from alembic.util.exc import CommandError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.database import Database
from app.models import Change, Event, Notification, Participation, Workshop
from app.seeds import EVENT_ID, seed_demo
from app.services import DomainError, change_workshop_location, load_graph
from src.impact import compute_impacted_set


def parser():
    result = argparse.ArgumentParser(
        description="Initialisation et vérification locale d’ImpactFlow"
    )
    result.add_argument(
        "--database-url",
        help="URL SQLite absolue ; sinon DATABASE_URL ou var/impactflow.sqlite3",
    )
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="Appliquer les migrations, sans effacer les données")
    sub.add_parser("seed-demo", help="Insérer les fixtures fictives dans une base vide")
    inspect = sub.add_parser(
        "inspect", help="Afficher l’état durable et un impact BFS en JSON"
    )
    inspect.add_argument("--event", default=EVENT_ID)
    inspect.add_argument("--workshop", default="w1")
    change = sub.add_parser(
        "set-workshop-location",
        help="Écriture locale de vérification, sans notification",
    )
    change.add_argument("--event", required=True)
    change.add_argument("--workshop", required=True)
    change.add_argument("--actor", required=True)
    change.add_argument("--location", required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    database = None
    try:
        settings = (
            Settings(database_url=args.database_url)
            if args.database_url
            else Settings.from_env()
        )
        database = Database(settings.database_url)
        if args.command == "init-db":
            database.initialize()
            database.check_schema()
            print(
                "Base initialisée ; schéma à jour. Aucune donnée existante supprimée."
            )
            return 0
        database.check_schema()
        if args.command == "seed-demo":
            with database.transaction() as session:
                created = seed_demo(session)
            print(
                "Démonstration créée : deux événements, données fictives, aucun e-mail envoyé."
                if created
                else "Démonstration déjà présente ; aucune donnée écrasée."
            )
        elif args.command == "inspect":
            with database.sessions() as session:
                graph = load_graph(session, args.event)
                impact = compute_impacted_set(graph, args.workshop)
                report = {
                    "event_id": args.event,
                    "events_in_database": session.scalar(
                        select(func.count()).select_from(Event)
                    ),
                    "confirmed_participants": session.scalar(
                        select(func.count())
                        .select_from(Participation)
                        .where(
                            Participation.event_id == args.event,
                            Participation.status == "confirmed",
                        )
                    ),
                    "workshops": {
                        w.id: {"name": w.name, "location": w.location}
                        for w in session.scalars(
                            select(Workshop)
                            .where(Workshop.event_id == args.event)
                            .order_by(Workshop.id)
                        )
                    },
                    "impacted_workshops": sorted(impact.impacted_workshop_ids),
                    "impacted_participants": sorted(impact.impacted_participant_ids),
                    "changes": [
                        {
                            "id": c.id,
                            "workshop_id": c.workshop_id,
                            "actor_id": c.actor_id,
                            "field": c.field,
                            "old_value": c.old_value,
                            "new_value": c.new_value,
                            "created_at": c.created_at.isoformat(),
                        }
                        for c in session.scalars(
                            select(Change)
                            .where(Change.event_id == args.event)
                            .order_by(Change.created_at, Change.id)
                        )
                    ],
                    "notification_count": session.scalar(
                        select(func.count())
                        .select_from(Notification)
                        .where(Notification.event_id == args.event)
                    ),
                    "external_emails_sent": 0,
                }
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            with database.transaction() as session:
                change = change_workshop_location(
                    session, args.event, args.workshop, args.actor, args.location
                )
            print(
                f"Changement {change.id} conservé avec son historique ; aucun e-mail envoyé."
                if change
                else "Valeur identique ; aucun changement ni notification créé."
            )
        return 0
    except (DomainError, ValueError, RuntimeError) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print(
            "Erreur : base inaccessible ou écriture invalide. Vérifier la configuration, les droits et init-db.",
            file=sys.stderr,
        )
        return 2
    except CommandError:
        print(
            "Erreur : migration impossible. Vérifier la version du code et restaurer une sauvegarde compatible si nécessaire.",
            file=sys.stderr,
        )
        return 2
    except OSError:
        print(
            "Erreur : impossible d’accéder au dossier de la base. Vérifier le chemin et les droits.",
            file=sys.stderr,
        )
        return 2
    finally:
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())
