#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
# Sélection explicite : ne pas reprendre une DATABASE_URL de travail exportée.
demo_directory="${DEMO_DIRECTORY:-$PWD/var/demo-prete}"
venv/bin/python -m app.demo --directory "$demo_directory"
# Résoudre aussi un DEMO_DIRECTORY relatif avant la validation de Settings.
export DATABASE_URL="$(venv/bin/python -c 'import sys; from pathlib import Path; print("sqlite:///" + str(Path(sys.argv[1]).resolve() / "impactflow.sqlite3"))' "$demo_directory")"
exec ./scripts/run_demo.sh
