#!/bin/bash
# Variant-vs-baseline pairs on real decks. Usage: play/launch_pairs.sh RUN DECKDIR SEEDBASE TAG a1/b1 a2/b2 ...
# VARIANT (env, default "plan") names the variant's match.py flags without the seat suffix, e.g. VARIANT="facts check"
# for --facts-a --check-a on the variant seat; the other seat plays the plain player.
# Logs go to /tmp/claude-0/TAG_N.out; /tmp/claude-0/TAG_batch.done appears when every part has finished.
# Each deck pair is two parts of 2 games with the same seats and decks, the variant on seat A in one part and on seat B in
# the other, so each variant plays each deck once on the play and once on the draw. 6 parts at a time.
cd /home/claude/mtg-ai
VARIANT=${VARIANT:-plan}
RUN=$1; D=$2; SEED=$3; TAG=$4; shift 4
specs=""; p=0
for pair in "$@"; do
  a=${pair%/*}; b=${pair#*/}
  for planseat in a b; do p=$((p+1)); specs="$specs $p:$a:$b:$planseat"; done
done
run_part() {
  IFS=: read p a b s <<< "$1"
  [ $p -le 6 ] && sleep $(( (p-1) * 5 ))  # stagger the first JVM boots (shared card database lock)
  F=""; for v in $VARIANT; do F="$F --$v-$s"; done
  python3 play/match.py --runtime /root/xmage/xmage/mage-server --classes /tmp/xmage-cls --a claude --b claude \
    --deck-a $D/$a.dck --deck-b $D/$b.dck $F --games 2 --seed $((SEED+p)) --model claude-opus-5-5 --effort high \
    --out $RUN/part$(printf %02d $p) > /tmp/claude-0/${TAG}_$p.out 2>&1
  echo "DONE $?" >> /tmp/claude-0/${TAG}_$p.out
}
export -f run_part; export RUN D SEED TAG VARIANT
echo $specs | tr ' ' '\n' | xargs -P 6 -I{} bash -c 'run_part {}; sleep 2'
echo "BATCH DONE" > /tmp/claude-0/${TAG}_batch.done
