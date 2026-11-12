#!/usr/bin/env bash
# Builds Playmat (github.com/arcanite24/playmat) at the pinned commit (PLAYMAT_COMMIT) with our changes, into
# $OUT/app (default ~/playmat-run/build/app), laid out like Playmat's desktop app:
#
#   - patches/*.patch: the Claude player type, an option for the launcher to pass JVM flags to the server, and the
#     web client's opponent picker (Playmat AI, Claude AI, Claude vs Playmat AI to watch)
#   - our two XMage rule fixes (engine/xmage/BecomesFaceDownCreatureEffect.java, VeteranSurvivor.java), copied over
#     Playmat's sources so its games follow the same rules as our recorded games (both XMage 1.4.62)
#   - our DSK decks as starter decks (dsk_starters.py)
#   - plugins/mage-player-mtgai.jar: ClaudeSeat, RecordedHuman, RecordedMad, GameRecorder (java/) and the PySeat,
#     Observer and AbilityKeys they use (engine/xmage), with config.xml pointing Human, Computer - mad and the new
#     Computer - claude at them
#
#   engine/playmat/apply_and_build.sh            # PLAYMAT=~/dev/playmat OUT=~/playmat-run/build
#
# WARNING: resets the Playmat checkout to the pinned commit (tracked files), so keep no work of your own in it.
# Needs JDK 17+ (JAVA_HOME, default Homebrew's openjdk@21), Maven, Node 22+ and python3. The first build takes a few
# minutes (the card sets); later ones are incremental.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
PLAYMAT=${PLAYMAT:-$HOME/dev/playmat}
OUT=${OUT:-$HOME/playmat-run/build}
SHA=$(cat "$HERE/PLAYMAT_COMMIT")
export JAVA_HOME=${JAVA_HOME:-/opt/homebrew/opt/openjdk@21}
export PATH=$JAVA_HOME/bin:$PATH
PY=${PYTHON:-python3}

[ -d "$PLAYMAT/.git" ] || git clone -q https://github.com/arcanite24/playmat.git "$PLAYMAT"
cd "$PLAYMAT"
git cat-file -e "$SHA^{commit}" 2>/dev/null || git fetch -q origin
git checkout -q -f --detach "$SHA"
# files a previous build's patches added (sources only: node_modules and target/ stay for incremental builds)
git clean -fdq -- Mage.Web.Client/public/starter-decks Mage.Web.Client/public/data Mage.Web.Client/src Mage/src Mage.Common/src Mage.Server/src Mage.Sets/src
for p in "$HERE"/patches/*.patch; do git apply "$p"; done
cp "$ROOT/engine/xmage/BecomesFaceDownCreatureEffect.java" Mage/src/main/java/mage/abilities/effects/common/continuous/
cp "$ROOT/engine/xmage/VeteranSurvivor.java" Mage.Sets/src/mage/cards/v/
cp "$ROOT/engine/xmage/Exile.java" Mage/src/main/java/mage/game/
"$PY" "$HERE/dsk_starters.py" "$PLAYMAT"

echo "building the server"
mvn -B -q -T 1C -pl '!Mage.Client,!Mage.Server.Console,!Mage.Tests,!Mage.Verify,!Mage.Reports' install -DskipTests
(cd Mage.Server && mvn -B -q package assembly:single -DskipTests)
echo "building the web client"
(cd Mage.Web.Client && npm ci --no-audit --no-fund --loglevel=error && npm run build --silent)
ops/desktop/build-app.sh "mtgai-${SHA:0:7}" "$OUT"

echo "building our seat plugin"
APP=$OUT/app
cls=$(mktemp -d)
trap 'rm -rf "$cls"' EXIT
CP=$(ls "$APP"/server/lib/*.jar "$APP"/server/plugins/*.jar | tr '\n' ':')
javac -nowarn -encoding UTF-8 -cp "$CP" -sourcepath "$ROOT/engine/xmage" -d "$cls/classes" \
    "$ROOT/engine/xmage/PySeat.java" "$ROOT/engine/xmage/Observer.java" "$ROOT/engine/xmage/AbilityKeys.java" "$HERE"/java/*.java
# our classes extend HumanPlayer and XMage's AI, which live in their own plugin jars: the manifest puts them on the
# plugin class loader with ours
HUMAN=$(cd "$APP/server/plugins" && ls mage-player-human-*.jar)
MAD=$(cd "$APP/server/plugins" && ls mage-player-ai-mad-*.jar)
printf 'Class-Path: %s %s\n' "$HUMAN" "$MAD" > "$cls/manifest.txt"
jar --create --file "$APP/server/plugins/mage-player-mtgai.jar" --manifest "$cls/manifest.txt" -C "$cls/classes" .

"$PY" - "$APP/server/config/config.xml" <<'EOF'
import re, sys
p = sys.argv[1]; s = open(p).read()
types = ('        <playerType name="Human" jar="mage-player-mtgai.jar" className="RecordedHuman"/>\n'
         '        <playerType name="Computer - mad" jar="mage-player-mtgai.jar" className="RecordedMad"/>\n'
         '        <playerType name="Computer - claude" jar="mage-player-mtgai.jar" className="ClaudeSeat"/>\n')
s, n = re.subn(r'\s*<playerType name="Human"[^>]*/>\s*<playerType name="Computer - mad"[^>]*/>\s*', '\n' + types, s)
assert n == 1, "config.xml: Human and Computer - mad entries not found"
open(p, "w").write(s)
EOF
grep -n "playerType " "$APP/server/config/config.xml"
# card pictures served by the site itself (fetch_card_images.py), so a Scryfall outage doesn't blank the cards
ln -sfn "${CARD_IMAGES:-$HOME/mtg-data/card-images}" "$APP/web/card-images"
echo "built $APP (Playmat ${SHA:0:7}, mtg-ai $(git -C "$ROOT" rev-parse --short HEAD))"
