#!/usr/bin/env bash
# Undoes install.sh: removes the two system daemons and puts the tunnel back as bobkim's login item. Playmat keeps
# running until the next logout or restart (start it with engine/playmat/run.sh after that, as before).
#
#   sudo bash ~/dev/mtg-ai/engine/playmat/launchd/uninstall.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
USER_ID=$(id -u bobkim)
for name in sh.devpick.playmat-tunnel sh.devpick.playmat; do
  launchctl bootout "system/$name" 2>/dev/null || true
  rm -f "/Library/LaunchDaemons/$name.plist"
  echo "removed $name"
done
AGENT=/Users/bobkim/Library/LaunchAgents/sh.devpick.playmat-tunnel.plist
BACKUP=/Users/bobkim/playmat-run/tunnel/sh.devpick.playmat-tunnel.agent.plist
if [ -f "$BACKUP" ]; then
  install -m 644 -o bobkim -g staff "$BACKUP" "$AGENT"
  launchctl bootstrap "gui/$USER_ID" "$AGENT" 2>/dev/null || echo "log in as bobkim to start the tunnel login item"
  echo "tunnel back as a login item"
fi
