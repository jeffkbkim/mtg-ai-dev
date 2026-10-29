#!/usr/bin/env bash
# Starts (or stops) our Playmat in the background: the Claude service, then Playmat's launcher, headless, which runs
# the game server and serves the web client on port 17170 to this computer and the home network. Both keep running
# after the terminal closes; `caffeinate -i -w` keeps the Mac from idle-sleeping while the launcher runs.
#
#   engine/playmat/run.sh          start (restarts what is already running)
#   engine/playmat/run.sh stop
#
# PLAY_DRAW=rule (default: Claude always plays first) or claude (the model chooses).
# PRIMER=v2 (default since 2026-10-24, after the puzzle test in notes/puzzles-v1-vs-v2-2026-10-24.md) or v1.
# Data: $PLAYMAT_DATA (default ~/playmat-run/data): accounts off (sign in with a name), server and service logs.
# Recordings: $MTGAI_RECORD_DIR (default ~/mtg-data/playmat-games)/<date>/<game id>/ (see java/GameRecorder.java).
# Quick Draft: the draft-brain service (play/draft_brain) on $DRAFT_BRAIN_PORT (default 17190); drafts are recorded under
# $MTGAI_DRAFT_DIR (default ~/mtg-data/playmat-drafts).
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
OUT=${OUT:-$HOME/playmat-run/build}
DATA=${PLAYMAT_DATA:-$HOME/playmat-run/data}
REC=${MTGAI_RECORD_DIR:-$HOME/mtg-data/playmat-games}
JAVA_HOME=${JAVA_HOME:-/opt/homebrew/opt/openjdk@21}
PY=${PYTHON:-/opt/homebrew/bin/python3}
PORT=${CLAUDE_PORT:-17180}
BRAIN_PORT=${DRAFT_BRAIN_PORT:-17190}
DRAFTS=${MTGAI_DRAFT_DIR:-$HOME/mtg-data/playmat-drafts}
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"   # claude, for the service

stop() {
  for name in launcher claude_service draft_brain; do
    f=$DATA/$name.pid
    if [ -f "$f" ] && kill -0 "$(cat "$f")" 2>/dev/null; then
      pid=$(cat "$f")
      kill "$pid" 2>/dev/null || true
      # the launcher stops its game server before it exits, and holds a lock until then
      for _ in $(seq 1 60); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
      echo "stopped $name"
    fi
    rm -f "$f"
  done
  # the launcher stops its game server when it quits; wait for the ports to free up
  for _ in $(seq 1 30); do
    lsof -nP -iTCP:17170 -iTCP:17172 -iTCP:"$PORT" -iTCP:"$BRAIN_PORT" -sTCP:LISTEN >/dev/null 2>&1 || return 0
    sleep 1
  done
}

stop
[ "${1:-start}" = stop ] && exit 0

mkdir -p "$DATA" "$REC" "$DRAFTS"
grep -q '^accounts=' "$DATA/settings.properties" 2>/dev/null || echo 'accounts=false' >> "$DATA/settings.properties"
grep -q '^memory=' "$DATA/settings.properties" 2>/dev/null || echo 'memory=4g' >> "$DATA/settings.properties"

PRIMER=${PRIMER:-v2} nohup "$PY" "$HERE/claude_service.py" --port "$PORT" --play-draw "${PLAY_DRAW:-rule}" >> "$DATA/claude_service.log" 2>&1 &
echo $! > "$DATA/claude_service.pid"
# no subshell: one would hold the caller's output open as long as the service runs
nohup /opt/homebrew/bin/uv run --directory "$ROOT" --group brain python -m play.draft_brain.server --port "$BRAIN_PORT" \
  < /dev/null >> "$DATA/draft_brain.log" 2>&1 &
echo $! > "$DATA/draft_brain.pid"

export PLAYMAT_DATA=$DATA
# the public name in front of this launcher (Cloudflare tunnel, behind Cloudflare Access): the game server accepts it
export PLAYMAT_EXTRA_ORIGINS=${PLAYMAT_EXTRA_ORIGINS:-https://play.devpick.sh}
export PLAYMAT_SERVER_OPTS="-Dmtgai.recordDir=$REC -Dmtgai.claudePort=$PORT -Dmtgai.draftBrainPort=$BRAIN_PORT -Dmtgai.draftDir=$DRAFTS -Dmtgai.playmatSha=$(cat "$HERE/PLAYMAT_COMMIT") -Dmtgai.codeSha=$(git -C "$ROOT" rev-parse HEAD)"
nohup "$JAVA_HOME/bin/java" -jar "$OUT/app/playmat-launcher.jar" --headless --no-browser >> "$DATA/launcher.out" 2>&1 &
echo $! > "$DATA/launcher.pid"
# keep the Mac from idle-sleeping while the launcher runs (no setting changed; ends with the launcher)
nohup caffeinate -i -w "$(cat "$DATA/launcher.pid")" >/dev/null 2>&1 &

echo "starting; the server is ready when this answers: curl -s localhost:17170 | head -1"
echo "open http://$(scutil --get LocalHostName 2>/dev/null || hostname -s).local:17170 from another computer on the network"
echo "logs: $DATA/launcher.out, $DATA/logs/server.log, $DATA/claude_service.log, $DATA/draft_brain.log"
