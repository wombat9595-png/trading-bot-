#!/usr/bin/env bash
# Run the firm 24/7 on this Mac with launchd.
#
#   bash scripts/service.sh start     install + start (also starts at every login, restarts on crash)
#   bash scripts/service.sh stop      stop it and keep it stopped (open paper positions are closed first)
#   bash scripts/service.sh status    is it running, what is it doing
#
# Two jobs: com.tradingbot.firm (the firm + control room) and com.tradingbot.report (9pm Telegram report).
# Logs: logs/firm.log, logs/firm.err.log, logs/report.log
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
FIRM=com.tradingbot.firm
REPORT=com.tradingbot.report

write_plists() {
  mkdir -p "$AGENTS" "$ROOT/logs"
  cat > "$AGENTS/$FIRM.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$FIRM</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$ROOT/scripts/run_service.sh</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ExitTimeOut</key><integer>45</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$ROOT/logs/firm.log</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/firm.err.log</string>
</dict></plist>
PLIST
  cat > "$AGENTS/$REPORT.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$REPORT</string>
  <key>ProgramArguments</key><array><string>$ROOT/.venv/bin/python</string><string>-m</string><string>desk</string><string>report</string></array>
  <key>WorkingDirectory</key><string>$ROOT/src</string>
  <key>EnvironmentVariables</key><dict><key>PYTHONUNBUFFERED</key><string>1</string></dict>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$ROOT/logs/report.log</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/report.log</string>
</dict></plist>
PLIST
}

loaded() { launchctl print "$DOMAIN/$1" >/dev/null 2>&1; }

case "${1:-}" in
  start)
    write_plists
    for job in $FIRM $REPORT; do
      loaded $job && launchctl bootout "$DOMAIN/$job" 2>/dev/null || true
      for _ in 1 2 3 4 5 6 7 8 9 10; do loaded $job || break; sleep 1; done
      launchctl bootstrap "$DOMAIN" "$AGENTS/$job.plist"
    done
    echo "Started. Control room: http://127.0.0.1:8050   Logs: $ROOT/logs/firm.log"
    ;;
  stop)
    for job in $FIRM $REPORT; do
      loaded $job && launchctl bootout "$DOMAIN/$job" 2>/dev/null || true
    done
    rm -f "$AGENTS/$FIRM.plist" "$AGENTS/$REPORT.plist"     # so it does not come back at next login
    echo "Stopped. It will not start again until you run: bash $ROOT/scripts/service.sh start"
    ;;
  status)
    if loaded $FIRM; then
      pid=$(launchctl print "$DOMAIN/$FIRM" | awk '/^[[:space:]]*pid = /{print $3}')
      echo "Firm service: loaded, ${pid:+running (pid $pid)}${pid:-NOT running (launchd will retry)}"
    else
      echo "Firm service: not installed (stopped)"
    fi
    loaded $REPORT && echo "9pm report: scheduled" || echo "9pm report: not scheduled"
    if [ -f "$ROOT/state/desk.json" ]; then
      "$ROOT/.venv/bin/python" - "$ROOT/state/desk.json" <<'PY'
import json, sys
from datetime import datetime, timezone
d = json.load(open(sys.argv[1]))
age = (datetime.now(timezone.utc) - datetime.fromisoformat(d["updated"])).total_seconds()
print(f"Last heartbeat: {age:.0f}s ago | paused: {d.get('paused')} | open positions: {len(d.get('open', []))} | "
      f"today ${d.get('today_realised', 0):+.2f} | all time ${d.get('lifetime_realised', 0):+.2f}")
PY
    fi
    echo "--- last 8 log lines ---"
    tail -n 8 "$ROOT/logs/firm.log" 2>/dev/null || echo "(no log yet)"
    ;;
  *) echo "usage: bash scripts/service.sh start|stop|status"; exit 1 ;;
esac
