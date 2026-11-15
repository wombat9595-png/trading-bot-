#!/usr/bin/env bash
# One-time setup on your MacBook. Run from the repo folder:  bash scripts/setup_mac.sh
set -euo pipefail
cd "$(dirname "$0")/.."
command -v python3 >/dev/null || { echo "Install Python 3.11+ first: https://www.python.org/downloads/"; exit 1; }
python3 -m venv .venv
. .venv/bin/activate
pip install -q --upgrade pip
pip install -q -e ".[ai,dev]"
[ -f .env ] || cp .env.example .env
pytest -q
echo
echo "Setup done. Next: open .env and paste your keys, then run:  bash scripts/start.sh"
