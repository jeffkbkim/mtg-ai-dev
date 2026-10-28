#!/usr/bin/env bash
# Run by the sh.devpick.playmat system daemon: every 30 s, if Playmat's launcher isn't running, start Playmat with
# engine/playmat/run.sh (which also starts the Claude service). A deploy (deploy_next.sh) holds
# ~/playmat-run/data/deploying while it stops, swaps and restarts, and this leaves Playmat alone meanwhile.
set -u
HERE=$(cd "$(dirname "$0")/.." && pwd)
DATA=${PLAYMAT_DATA:-$HOME/playmat-run/data}
while true; do
  if [ -f "$DATA/deploying" ] && [ -z "$(find "$DATA/deploying" -mmin +15 2>/dev/null)" ]; then
    :  # a deploy is under way (a lock older than 15 minutes is stale and ignored)
  elif ! { [ -f "$DATA/launcher.pid" ] && kill -0 "$(cat "$DATA/launcher.pid")" 2>/dev/null; }; then
    echo "$(date '+%F %T') launcher down: starting Playmat"
    "$HERE/run.sh" || echo "$(date '+%F %T') run.sh failed"
  fi
  sleep 30
done
