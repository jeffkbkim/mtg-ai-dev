#!/bin/zsh
# Nightly soak: if the seat code on main changed since the last nightly, rebuild, run every *Check and the full
# 2,400-game soak, and compare with the previous nightly. Writes ~/mtg-data/soak/nightly/latest.md, whose first
# line is "NEW PROBLEMS", "NO NEW PROBLEMS" or "SKIPPED".
#   zsh experiments/coverage_soak/nightly.sh
set -u
export PATH=/opt/homebrew/opt/openjdk@21/bin:$HOME/.local/bin:/opt/homebrew/bin:$PATH
REPO=${0:A:h:h:h}
N=$HOME/mtg-data/soak/nightly
R=$HOME/xmage/xmage/mage-server
CLS=$HOME/mtg-data/soak/nightly/classes   # own build dir, so other work on /tmp/xmage-cls can't change a running soak
mkdir -p $N
cd $REPO
git pull -q --ff-only origin main || { print "SKIPPED\n\ngit pull failed in $REPO (local changes or diverged branch)" > $N/latest.md; exit 1; }
HEAD=$(git rev-parse --short HEAD)
LAST=$(cat $N/last_commit 2>/dev/null)
if [[ -n $LAST ]] && git diff --quiet $LAST HEAD -- engine/xmage experiments/coverage_soak; then
  print "SKIPPED\n\nNo seat or soak change since $LAST (main is $HEAD)." > $N/latest.md; exit 0
fi
CP=$(find $R -name '*.jar' | tr '\n' ':')
rm -rf $CLS && mkdir -p $CLS && javac -cp "$CP" -d $CLS engine/xmage/*.java 2> $N/javac.log || { print "NEW PROBLEMS\n\n- seat code does not compile at $HEAD (see $N/javac.log)" > $N/latest.md; exit 1; }
CHECKS=""
for f in engine/xmage/*Check.java; do
  c=${f:t:r}; [[ $c == BlockCheck ]] && continue   # BlockCheck is a tool that needs a board, not a regression check
  r=$(cd $R && java -Djava.awt.headless=true -cp $CLS:$CP $c 2>&1 | grep -E '^(PASS|FAIL)' | tail -1)
  CHECKS+="- $c: ${r:-no result}\n"
done
OUT=$HOME/mtg-data/soak/nightly-$(date +%Y-%m-%d)-$HEAD
uv run python experiments/coverage_soak/soak.py --runs 600 --games 4 --jobs 2 --seed 1 --classes $CLS --out $OUT > $OUT.log 2>&1
uv run python experiments/coverage_soak/report.py $OUT > /dev/null
BASE=$(cat $N/last_dir 2>/dev/null || echo $HOME/mtg-data/soak/full-2026-10-22)
SUMMARY=$(uv run python experiments/coverage_soak/compare.py $BASE $OUT)
if print -- "$CHECKS" | grep -q -E ': (FAIL|no result)'; then
  SUMMARY="NEW PROBLEMS\n- a regression check failed (see Checks below)\n${SUMMARY#*PROBLEMS}"
fi
print "$SUMMARY\n\nmain $HEAD, compared with $BASE. Output: $OUT\n\nChecks:\n$CHECKS" > $N/latest.md
print $HEAD > $N/last_commit
print $OUT > $N/last_dir
cat $N/latest.md
