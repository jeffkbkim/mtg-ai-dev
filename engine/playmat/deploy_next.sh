#!/usr/bin/env bash
# Deploys ~/playmat-run/build-next (made by OUT=~/playmat-run/build-next apply_and_build.sh) when no game is in progress: stops Playmat, keeps the current build as build-prev (rollback: swap the folders back, run.sh),
# starts the new one. No waiting: it refuses instead (Jeff, 2026-10-24: a person says go).
#
#   engine/playmat/deploy_next.sh --go      # only after checking no one is playing; refuses if a game log changed in the last 10 minutes
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
RUN=$HOME/playmat-run
REC=${MTGAI_RECORD_DIR:-$HOME/mtg-data/playmat-games}
[ -d "$RUN/build-next/app" ] || { echo "no $RUN/build-next/app"; exit 1; }
# A game counts as active while any recording's game log changed in the last 10 minutes, whatever its result file says
# (2026-10-24: checking only the 5 newest folders by mtime missed a live game after old folders were rewritten).
active() { find "$REC" -name game_log.jsonl -mmin -10 2>/dev/null | grep -q .; }
[ "${1:-}" = "--go" ] || { echo "refusing: deploys need an explicit --go after a person checked no game is running"; exit 2; }
if active; then echo "a game was active in the last 10 minutes: not deployed"; find "$REC" -name game_log.jsonl -mmin -10; exit 2; fi
# the sh.devpick.playmat daemon (launchd/supervise.sh) leaves Playmat alone while this lock is held
DATA=${PLAYMAT_DATA:-$RUN/data}
touch "$DATA/deploying"; trap 'rm -f "$DATA/deploying"' EXIT
"$HERE/run.sh" stop
rm -rf "$RUN/build-prev"
mv "$RUN/build" "$RUN/build-prev"
mv "$RUN/build-next" "$RUN/build"
"$HERE/run.sh"
for _ in $(seq 1 90); do lsof -nP -iTCP:17172 -sTCP:LISTEN >/dev/null 2>&1 && break; sleep 2; done
lsof -nP -iTCP:17172 -sTCP:LISTEN >/dev/null 2>&1 && echo "deployed $(date)" || { echo "server did not come up"; exit 3; }
