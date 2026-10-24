#!/usr/bin/env bash
# A test Playmat server beside the live one, for checking a build before deploying it: XMage on 27171/27172 (and
# health 27173) from $B (default ~/playmat-run/build-next/app), its own Claude service on 27180, recordings under
# ~/playmat-run/test/rec. Serve the web client from the Playmat checkout with
#   cd ~/dev/playmat/Mage.Web.Client && VITE_MAGE_SERVER_URL=ws://127.0.0.1:27172 npx vite --port 4180
#
#   engine/playmat/test_server.sh [stop]
set -euo pipefail
T=$HOME/playmat-run/test; B=${B:-$HOME/playmat-run/build-next/app}
JAVA=/opt/homebrew/opt/openjdk@21/bin/java
for f in $T/server.pid $T/claude.pid; do [ -f $f ] && kill $(cat $f) 2>/dev/null || true; done
sleep 3
[ "${1:-}" = stop ] && exit 0
mkdir -p $T/server/db $T/rec
rm -rf $T/server/config $T/server/plugins
cp -R $B/server/config $B/server/plugins $T/server/
[ -f $T/server/db/cards.h2.mv.db ] || cp $HOME/playmat-run/data/server/db/cards.h2.mv.db $T/server/db/
/opt/homebrew/bin/python3 - $T/server/config/config.xml <<'PY'
import re,sys
p=sys.argv[1]; s=open(p).read()
s=re.sub(r'port="17171"','port="27171" websocketPort="27172" websocketAllowedOrigins="http://localhost:4180,http://127.0.0.1:4180,http://localhost:4181,http://127.0.0.1:4181,http://localhost:4182,http://127.0.0.1:4182,http://localhost:4183,http://127.0.0.1:4183,http://localhost:5180,http://127.0.0.1:5180,http://192.168.1.82:5180"',s,1)
s=s.replace('authenticationActivated="true"','authenticationActivated="false"')
open(p,'w').write(s)
PY
cd $T/server
PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" nohup /opt/homebrew/bin/python3 $HOME/dev/mtg-ai/engine/playmat/claude_service.py --port 27180 >> $T/claude.log 2>&1 &
echo $! > $T/claude.pid
nohup $JAVA -Xmx3g -Dfile.encoding=UTF-8 -Djava.awt.headless=true -Dxmage.testMode=false -Dxmage.healthPort=27173 \
  -Dmtgai.recordDir=$T/rec -Dmtgai.claudePort=27180 -Dmtgai.playmatSha=test -Dmtgai.codeSha=test ${EXTRA_OPTS:-} \
  -cp "$B/server/lib/*" mage.server.Main >> $T/server.log 2>&1 &
echo $! > $T/server.pid
echo started
