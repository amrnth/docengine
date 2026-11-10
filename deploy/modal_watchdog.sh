#!/bin/bash
# Stop every live docengine Modal app at the deadline; exit early once nothing is running.
cd "$(dirname "$0")/.."
DEADLINE=$(( $(date +%s) + ${1:-9000} ))
live() { .venv/bin/modal app list --json 2>/dev/null | python3 -c "import json,sys;[print(a['app_id']) for a in json.load(sys.stdin) if a['description']=='docengine' and a['state'] not in ('stopped','stopping')]"; }
while [ $(date +%s) -lt $DEADLINE ]; do
  if [ -z "$(live)" ] && ! pgrep -f "modal_app.py" >/dev/null; then echo "all done, nothing live $(date)"; exit 0; fi
  sleep 60
done
for id in $(live); do .venv/bin/modal app stop $id && echo "watchdog stopped $id $(date)"; done
