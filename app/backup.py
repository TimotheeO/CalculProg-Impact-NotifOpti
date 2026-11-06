"""Sauvegarde SQLite cohérente, y compris avec journal WAL, sans écrasement."""

import argparse
import sqlite3
import sys
from pathlib import Path


def copy_database(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file() or source == destination:
        raise ValueError(
            "Sélectionnez une base source existante et une nouvelle destination."
        )
    if destination.exists():
        raise ValueError("La destination existe déjà. Aucune base n’a été remplacée.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        if (
            original.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            or original.execute("PRAGMA foreign_key_check").fetchall()
        ):
            raise ValueError("La base source ne passe pas les contrôles d’intégrité.")
        original.execute("SELECT version_num FROM alembic_version").fetchone()
        # Création exclusive : ne jamais écraser une base apparue entre les contrôles.
        with destination.open("xb"):
            destination.chmod(0o600)
        try:
            with sqlite3.connect(destination) as target:
                original.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError(
                        "La sauvegarde ne passe pas le contrôle d’intégrité."
                    )
        except Exception:
            destination.unlink(
                missing_ok=True
            )  # Uniquement le fichier incomplet créé ici.
            raise
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Sauvegarder ou restaurer une base vers un nouveau fichier, sans écrasement."
    )
    parser.add_argument("action", choices=("sauvegarder", "restaurer"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    try:
        destination = copy_database(args.source, args.destination)
    except (OSError, ValueError, sqlite3.Error) as error:
        print(
            "Copie refusée : source et intégrité à vérifier, destination neuve obligatoire. "
            + (str(error) if isinstance(error, ValueError) else ""),
            file=sys.stderr,
        )
        return 2
    print(f"Copie vérifiée : {destination}")
    print(
        "Pour une restauration, arrêtez le serveur puis sélectionnez explicitement ce nouveau fichier avec DATABASE_URL."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
