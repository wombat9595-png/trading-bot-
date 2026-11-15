#!/usr/bin/env bash
# What launchd runs. Not meant to be run by hand: use scripts/service.sh start|stop|status.
# Python is the main process (so launchd's stop signal reaches it and positions close cleanly);
# caffeinate rides along and exits when Python does.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs state journal
export PYTHONUNBUFFERED=1
/usr/bin/caffeinate -is -w $$ &        # no idle sleep; no system sleep while on mains power
cd src
echo "=== firm starting $(date '+%Y-%m-%d %H:%M:%S') ==="
if grep -q '^XAI_API_KEY=.\+' ../.env 2>/dev/null; then GROK=--grok; else GROK=; fi
exec ../.venv/bin/python -m desk run $GROK
