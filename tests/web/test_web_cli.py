import json
import os
import subprocess
import sys
from pathlib import Path

from app.cli import main

ROOT = Path(__file__).resolve().parents[2]


def test_real_process_restart_preserves_state_history_and_bfs(tmp_path):
    url = f"sqlite:///{tmp_path / 'persisted.sqlite3'}"

    def run(*args):
        result = subprocess.run(
            [sys.executable, "-m", "app.cli", "--database-url", url, *args],
            cwd=ROOT,
            env={**os.environ, "APP_ENV": "test"},
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    run("init-db")
    run("seed-demo")
    run(
        "set-workshop-location",
        "--event",
        "demo-rencontres",
        "--workshop",
        "w1",
        "--actor",
        "demo-thomas",
        "--location",
        "Salle Bordeaux",
    )
    run("init-db")  # Les migrations ne recréent pas les tables ni les données.
    assert "déjà présente" in run("seed-demo")
    report = json.loads(run("inspect"))
    assert report["events_in_database"] == 2
    assert report["confirmed_participants"] == 8
    assert report["workshops"]["w1"]["location"] == "Salle Bordeaux"
    assert report["impacted_participants"] == [
        "demo-alice",
        "demo-lina",
        "demo-mehdi",
        "demo-sofia",
    ]
    saved = next(c for c in report["changes"] if c["workshop_id"] == "w1")
    assert saved["old_value"] == "La Cuisine" and saved["new_value"] == "Salle Bordeaux"
    assert saved["actor_id"] == "demo-thomas" and saved["created_at"].endswith("+00:00")
    assert report["notification_count"] == 1 and report["external_emails_sent"] == 0


def test_cli_reports_missing_schema_without_traceback(tmp_path, capsys):
    code = main(
        ["--database-url", f"sqlite:///{tmp_path / 'empty.sqlite3'}", "inspect"]
    )
    captured = capsys.readouterr()
    assert code == 2 and captured.out == ""
    assert "init-db" in captured.err and "Traceback" not in captured.err


def test_cli_handles_an_unwritable_database_location(tmp_path, capsys):
    blocked = tmp_path / "file-instead-of-directory"
    blocked.write_text("keep")
    assert (
        main(["--database-url", f"sqlite:///{blocked / 'db.sqlite3'}", "init-db"]) == 2
    )
    assert "Erreur" in capsys.readouterr().err
    assert blocked.read_text() == "keep"


def test_cli_handles_unknown_event(seeded_db, capsys):
    assert main(["--database-url", seeded_db.url, "inspect", "--event", "missing"]) == 2
    assert "Événement introuvable" in capsys.readouterr().err


def test_cli_handles_an_unknown_migration_version(database, capsys):
    from sqlalchemy import text

    with database.engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num='future'"))
    assert main(["--database-url", database.url, "init-db"]) == 2
    captured = capsys.readouterr()
    assert "migration impossible" in captured.err
    assert "Traceback" not in captured.err
