#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
if venv/bin/python - <<'PY'
import json
import sys
import urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:8025/api/v1/info', timeout=2) as response:
        info = json.load(response)
    if not isinstance(info, dict) or not str(info.get('Version', '')).startswith('v'):
        sys.exit(1)
except (OSError, ValueError):
    sys.exit(1)
print('Mailpit est déjà actif sur http://127.0.0.1:8025 (' + info['Version'] + '). Instance conservée ; aucun message lu ou modifié.')
PY
then
  exit 0
fi
mailpit_binary="${MAILPIT_BINARY:-var/tools/mailpit-v1.31.6/mailpit}"
if [[ ! -x "$mailpit_binary" ]]; then
  cat >&2 <<'HELP'
Mailpit absent. Installation gratuite (Linux x86_64, GitHub CLI connecté) :
  mkdir -p var/tools/mailpit-v1.31.6
  gh release download v1.31.6 --repo axllent/mailpit --pattern mailpit-linux-amd64.tar.gz --dir var/tools/mailpit-v1.31.6
  tar -xzf var/tools/mailpit-v1.31.6/mailpit-linux-amd64.tar.gz -C var/tools/mailpit-v1.31.6 mailpit
Ou fournir MAILPIT_BINARY=/chemin/vers/mailpit.
HELP
  exit 2
fi
mkdir -p var/demo-cycle1
exec "$mailpit_binary" --listen 127.0.0.1:8025 --smtp 127.0.0.1:1025 \
  --database var/demo-cycle1/mailpit.sqlite3 --disable-version-check --smtp-disable-rdns
