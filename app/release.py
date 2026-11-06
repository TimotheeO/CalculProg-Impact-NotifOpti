"""Livraison locale reproductible, sans publier ni embarquer les données privées."""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import ROOT


def source_files():
    result = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    allowed = {
        "README.md",
        "VERSION",
        "requirements.txt",
        "constraints.txt",
        "alembic.ini",
        "pytest.ini",
        ".gitignore",
        ".env.example",
        "cli.py",
        "demo.py",
        "demo_pipeline.py",
    }
    prefixes = (
        "app/",
        "src/",
        "tests/",
        "scripts/",
        "data/",
        ".github/",
        "docs/maquettes/",
        "docs/preuves/cycle-2/",
    )
    paths = []
    for path in result.stdout.decode().split("\0"):
        relative = Path(path)
        source = ROOT / relative
        if not path or not source.is_file() or source.is_symlink():
            continue
        if path != ".env.example" and (
            relative.name.startswith(".env")
            or ".sqlite3" in relative.name
            or relative.suffix in {".pyc", ".png", ".pem", ".key"}
        ):
            continue
        if any(
            part in {"__pycache__", ".git", "venv", "var"} for part in relative.parts
        ):
            continue
        if path in allowed or path == "docs/DEMO.md" or path.startswith(prefixes):
            paths.append(path)
    return sorted(set(paths))


def prepare(directory, *, video=None):
    directory = Path(directory).resolve()
    if directory.exists():
        raise ValueError(
            "Choisissez un nouveau dossier de livraison ; aucun fichier remplacé."
        )
    files = source_files()
    version = (ROOT / "VERSION").read_text().strip()
    template = Environment(
        loader=FileSystemLoader(ROOT / "app" / "templates" / "release"),
        autoescape=select_autoescape(),
    ).get_template("slides.html")
    slides = template.render(version=version)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    manifest = {
        "version": version,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "base_commit": revision,
        "working_tree_modified": dirty,
        "published": False,
        "mode": "local-mailpit",
        "source_sha256": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in files
        },
    }
    if video:
        video = Path(video)
        if not video.is_file():
            raise ValueError("La vidéo indiquée est introuvable.")
        manifest["video_sha256"] = hashlib.sha256(video.read_bytes()).hexdigest()
    directory.mkdir(parents=True, mode=0o700)
    (directory / "soutenance.html").write_text(slides, encoding="utf-8")
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    archive = directory / f"ImpactFlow-{version}-local.zip"
    with ZipFile(archive, "x", compression=ZIP_DEFLATED) as bundle:
        for path in files:
            bundle.write(ROOT / path, path)
        bundle.writestr("soutenance.html", slides)
        bundle.writestr(
            "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
        )
        if video:
            bundle.write(video, "demo-secours.webm")
    (directory / "SHA256SUMS").write_text(
        hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n"
    )
    return archive


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Préparer une archive locale, un manifeste et le support de soutenance, sans push ni publication."
    )
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--video", type=Path)
    args = parser.parse_args(argv)
    try:
        archive = prepare(args.directory, video=args.video)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print("Livraison non créée : " + str(error), file=sys.stderr)
        return 2
    print(f"Livraison locale : {archive}")
    print("Aucune release GitHub, aucun tag ni push n’a été publié.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
