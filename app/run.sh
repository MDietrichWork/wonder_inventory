#!/usr/bin/env bash
# One-command launcher: create venv + install + seed (first run) + serve.
#   ./run.sh           start (seeds only if the DB is missing)
#   ./run.sh --seed    force a fresh re-seed, then start
set -euo pipefail
cd "$(dirname "$0")/backend"

if [ ! -d .venv ]; then
  echo "→ creating venv + installing deps…"
  python3 -m venv .venv
  ./.venv/bin/pip -q install --upgrade pip
  ./.venv/bin/pip -q install -r requirements.txt
fi

if [ ! -f wonder.db ] || [ "${1:-}" = "--seed" ]; then
  echo "→ seeding database (validation history)…"
  ./.venv/bin/python -m wonder.seed
fi

echo "→ serving at http://127.0.0.1:8000  (Ctrl-C to stop)"
exec ./.venv/bin/uvicorn wonder.main:app --host 127.0.0.1 --port 8000
