"""Livraison locale vérifiable et commandes de sauvegarde sans écrasement."""

import hashlib
import json
from zipfile import ZipFile

import pytest

from app.backup import main as backup_main
from app.release import prepare


def test_delivery_bundle_contains_current_source_slides_and_manifest_without_local_data(
    tmp_path,
):
    archive = prepare(tmp_path / "delivery")
    with ZipFile(archive) as bundle:
        names = bundle.namelist()
        assert {
            "README.md",
            "docs/DEMO.md",
            "soutenance.html",
            "manifest.json",
            ".env.example",
        } <= set(names)
        assert not any(
            name.startswith(("var/", "venv/", ".git/"))
            or name == ".env"
            or name.endswith((".sqlite3", ".png"))
            for name in names
        )
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["published"] is False and manifest["mode"] == "local-mailpit"
        for name, digest in manifest["source_sha256"].items():
            assert hashlib.sha256(bundle.read(name)).hexdigest() == digest
        assert "Le bon changement" in bundle.read("soutenance.html").decode()
    assert (
        (archive.parent / "SHA256SUMS")
        .read_text()
        .startswith(hashlib.sha256(archive.read_bytes()).hexdigest())
    )
    with pytest.raises(ValueError, match="nouveau dossier"):
        prepare(archive.parent)


def test_backup_command_succeeds_restore_refuses_existing_and_bad_source(
    seeded_db, tmp_path
):
    backup = tmp_path / "saved.sqlite3"
    assert backup_main(["sauvegarder", seeded_db.path, str(backup)]) == 0
    assert backup_main(["restaurer", str(backup), str(backup)]) == 2
    bad = tmp_path / "not-a-database"
    bad.write_text("aucune donnée SQLite")
    target = tmp_path / "untouched.sqlite3"
    assert backup_main(["restaurer", str(bad), str(target)]) == 2
    assert not target.exists()
