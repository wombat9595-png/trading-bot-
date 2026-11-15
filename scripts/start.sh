#!/usr/bin/env bash
# Start the whole firm + control room. Stop with Ctrl+C (all paper positions are closed cleanly).
# Keeps the Mac awake while running. Add --grok for X sentiment once XAI_API_KEY is in .env.
set -euo pipefail
cd "$(dirname "$0")/.."
. .venv/bin/activate
cd src
python -m desk doctor
echo "Control room: http://127.0.0.1:8050"
exec caffeinate -i python -m desk run "$@"
