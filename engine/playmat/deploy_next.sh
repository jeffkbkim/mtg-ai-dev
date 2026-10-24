#!/usr/bin/env bash
# Deploys ~/playmat-run/build-next (made by OUT=~/playmat-run/build-next apply_and_build.sh) once no recorded game is
# in progress: stops Playmat, keeps the current build as build-prev (rollback: swap the folders back, run.sh),
# starts the new one. A game in progress is a recording folder without games.jsonl among the 5 newest.
#
#   engine/playmat/deploy_next.sh [--wait-max <seconds>, default 3600]
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
RUN=$HOME/playmat-run
REC=${MTGAI_RECORD_DIR:-$HOME/mtg-data/playmat-games}
MAX=${2:-3600}
[ -d "$RUN/build-next/app" ] || { echo "no $RUN/build-next/app"; exit 1; }
running() {
  for d in $(ls -td "$REC"/*/*/ 2>/dev/null | head -5); do [ -f "$d/games.jsonl" ] || return 0; done
  return 1
}
waited=0
while running; do
  [ "$waited" -ge "$MAX" ] && { echo "a game is still in progress after ${MAX}s: not deployed"; exit 2; }
  sleep 10; waited=$((waited + 10))
done
"$HERE/run.sh" stop
rm -rf "$RUN/build-prev"
mv "$RUN/build" "$RUN/build-prev"
mv "$RUN/build-next" "$RUN/build"
"$HERE/run.sh"
for _ in $(seq 1 90); do lsof -nP -iTCP:17172 -sTCP:LISTEN >/dev/null 2>&1 && break; sleep 2; done
lsof -nP -iTCP:17172 -sTCP:LISTEN >/dev/null 2>&1 && echo "deployed $(date)" || { echo "server did not come up"; exit 3; }
