#!/usr/bin/env bash
# Moves the Playmat tunnel and Playmat itself from login items to system daemons, so a logout (e.g. a WindowServer
# crash) doesn't take play.devpick.sh or the game server down. Run once, with sudo, when no game is in progress:
#
#   sudo bash ~/dev/mtg-ai/engine/playmat/launchd/install.sh
#
# Both run as bobkim. The tunnel restarts (a few seconds of no play.devpick.sh); Playmat keeps running if it is up
# (the daemon only starts it when it is down). Undo: sudo bash ~/dev/mtg-ai/engine/playmat/launchd/uninstall.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
USER_ID=$(id -u bobkim)
AGENT=/Users/bobkim/Library/LaunchAgents/sh.devpick.playmat-tunnel.plist
BACKUP=/Users/bobkim/playmat-run/tunnel
mkdir -p "$BACKUP"
# the tunnel's login item: stop it and keep its plist for uninstall.sh
launchctl bootout "gui/$USER_ID/sh.devpick.playmat-tunnel" 2>/dev/null || true
[ -f "$AGENT" ] && mv "$AGENT" "$BACKUP/sh.devpick.playmat-tunnel.agent.plist"
for name in sh.devpick.playmat-tunnel sh.devpick.playmat; do
  install -m 644 -o root -g wheel "$HERE/$name.plist" "/Library/LaunchDaemons/$name.plist"
  launchctl bootout "system/$name" 2>/dev/null || true
  launchctl bootstrap system "/Library/LaunchDaemons/$name.plist"
  echo "installed $name"
done
sleep 5
launchctl print system/sh.devpick.playmat-tunnel | grep -E "state =|pid =" | head -2
launchctl print system/sh.devpick.playmat | grep -E "state =|pid =" | head -2
echo "done: play.devpick.sh and Playmat now run as system daemons"
