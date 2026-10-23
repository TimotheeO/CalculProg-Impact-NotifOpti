#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
export DATABASE_URL="${DATABASE_URL:-sqlite:///$PWD/var/demo-cycle1/impactflow.sqlite3}"
export APP_ENV=development
export APP_BASE_URL=http://127.0.0.1:8000
export MAILER_BACKEND=mailpit
export SMTP_HOST=127.0.0.1
export SMTP_PORT=1025
export MAILPIT_UI_URL=http://127.0.0.1:8025
export BATCH_WINDOW_SECONDS="${BATCH_WINDOW_SECONDS:-60}"
export SEND_MAX_PER_PERIOD=1
export SEND_PERIOD_SECONDS=1
export SEND_DAILY_LIMIT=300
export APP_WORKER_ENABLED=true
venv/bin/python -m app.cli init-db
venv/bin/python - <<'PY'
import sys
import urllib.request
from app.config import Settings
settings=Settings.from_env()
try:
    with urllib.request.urlopen(settings.mailpit_ui_url+'/readyz',timeout=3) as response:
        if response.status!=200:raise OSError()
except OSError:
    print('Mailpit indisponible. Démarrer scripts/mailpit.sh dans un autre terminal.',file=sys.stderr)
    sys.exit(2)
print(f'Application : {settings.base_url} ; Mailpit : {settings.mailpit_ui_url}')
print(f'Fenêtre fixe : {settings.batch_window_seconds:g} s ; débit global : 1 tentative/s.')
print('Guide unique : docs/DEMO.md ; préparation des comptes et parcours de démonstration.')
PY
exec venv/bin/python -m uvicorn app.web:create_app --factory --host 127.0.0.1 --port 8000
