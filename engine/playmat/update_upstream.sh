#!/usr/bin/env bash
# What Playmat's master has that our pin (PLAYMAT_COMMIT) doesn't, for the daily review (UPDATE.md):
# new commits, files changed per area (rules engine, XMage AI, DSK/SPG cards and set files, web client, server), and
# whether our patches still apply on the new head. Changes nothing outside a temporary worktree.
#
#   engine/playmat/update_upstream.sh [ref, default origin/master]     # PLAYMAT=~/dev/playmat
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
PLAYMAT=${PLAYMAT:-$HOME/dev/playmat}
PIN=$(cat "$HERE/PLAYMAT_COMMIT")
cd "$PLAYMAT"
git fetch -q --filter=blob:none origin master
NEW=$(git rev-parse "${1:-origin/master}")
echo "pin $PIN"
echo "new $NEW ($(git log -1 --format='%cd %s' --date=short "$NEW"))"
[ "$PIN" = "$NEW" ] && { echo "no new commits"; exit 0; }
echo "commits: $(git rev-list --count "$PIN..$NEW")"
git log --format='  %h %ad %s' --date=short "$PIN..$NEW" | head -60

area() {  # name, then paths
  local name=$1; shift
  local files
  files=$(git diff --name-only "$PIN" "$NEW" -- "$@" | wc -l | tr -d ' ')
  echo "$name: $files files, $(git rev-list --count "$PIN..$NEW" -- "$@") commits"
  [ "$files" -gt 0 ] && git diff --stat=120 "$PIN" "$NEW" -- "$@" | sed 's/^/    /' | tail -25
  return 0
}
echo
area "rules engine (Mage/src/main)" Mage/src/main
area "XMage AI" Mage.Server.Plugins/Mage.Player.AI Mage.Server.Plugins/Mage.Player.AI.MAD Mage.Server.Plugins/Mage.Player.AIMCTS
area "DSK and SPG set files" Mage.Sets/src/mage/sets/DuskmournHouseOfHorror.java Mage.Sets/src/mage/sets/SpecialGuests.java
area "server (Mage.Server, Mage.Common)" Mage.Server/src Mage.Common/src
area "web client" Mage.Web.Client/src
area "desktop launcher" ops/desktop

# card files of the cards our DSK games use (engine/vocab/dsk_card_text.json): class names as XMage writes them
python3 - "$PIN" "$NEW" "$ROOT/engine/vocab/dsk_card_text.json" <<'EOF'
import json, re, subprocess, sys
pin, new, vocab = sys.argv[1:]
changed = subprocess.run(["git", "diff", "--name-only", pin, new, "--", "Mage.Sets/src/mage/cards"],
                         capture_output=True, text=True, check=True).stdout.split()
def cls(name):  # "Fear of Being Hunted" -> FearOfBeingHunted, "Valgavoth's Onslaught" -> ValgavothsOnslaught
    return "".join(w[:1].upper() + w[1:] for w in re.sub(r"[^A-Za-z0-9 ]", "", name).split())
ours = {cls(c["name"].split(" // ")[0]) for c in json.load(open(vocab))}
hits = [f for f in changed if f.rsplit("/", 1)[-1].removesuffix(".java") in ours]
print(f"\ncard files: {len(changed)} changed, {len(hits)} of them DSK cards we play")
for f in hits:
    print("   ", f)
EOF

# do our patches still apply on the new head?
W=$(mktemp -d)/playmat-check
trap 'git -C "$PLAYMAT" worktree remove --force "$W" >/dev/null 2>&1 || true' EXIT
git worktree add -q --detach "$W" "$NEW"
echo
conflict=""
for p in "$HERE"/patches/*.patch; do
  if [ -n "$conflict" ]; then echo "not checked (after a conflict): $(basename "$p")"
  elif git -C "$W" apply --check "$p" 2>/dev/null; then git -C "$W" apply "$p"; echo "applies: $(basename "$p")"
  else conflict=1; echo "CONFLICT: $(basename "$p")"; { git -C "$W" apply --check "$p" 2>&1 || true; } | sed 's/^/    /' | head -5; fi
done

# for the security pass: dependency, build and install changes, and URLs the new code adds
echo
echo "security pass inputs:"
git -C "$PLAYMAT" diff --stat "$PIN" "$NEW" -- '*package.json' '*package-lock.json' '*pom.xml' 'ops/' '*.sh' '*.ps1' '*Dockerfile*' '.github/' | sed 's/^/    /' | tail -20
git -C "$PLAYMAT" diff "$PIN" "$NEW" -- . ':!*.test.*' ':!*.json' ':!*/public/*' ':!*.md' | grep -E '^\+.*https?://' | grep -vE 'localhost|127\.0\.0\.1|github\.com/arcanite24|scryfall|xmage|magic\.wizards' | sed 's/^/    new URL: /' | sort -u | head -30
