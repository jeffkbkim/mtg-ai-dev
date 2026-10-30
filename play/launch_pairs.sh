#!/bin/bash
# Variant-vs-baseline pairs on real decks. Usage: play/launch_pairs.sh RUN DECKDIR SEEDBASE TAG a1/b1 a2/b2 ...
# VARIANT (env, default "plan") names the variant's match.py flags without the seat suffix, e.g. VARIANT="facts check"
# for --facts-a --check-a on the variant seat; the other seat plays the plain player. A word with "=" passes a value,
# e.g. VARIANT="effort=medium" gives --effort-a medium. BOTH (env, same form) goes to both seats, e.g. BOTH="facts check".
# The match.py command line uses --effort high unless the variant overrides one seat.
# PARTS="31 32 35" (env) reruns only those parts with the same arguments.
# Logs go to /tmp/claude-0/TAG_N.out; /tmp/claude-0/TAG_batch.done appears when every part has finished.
# Each deck pair is two parts of GAMES games (default 2) with the same seats and decks, the variant on seat A in one part and on seat B in
# the other, so each variant plays each deck once on the play and once on the draw. 6 parts at a time.
cd /home/claude/mtg-ai
VARIANT=${VARIANT-plan}  # only when unset: VARIANT="" means no variant
GAMES=${GAMES:-2}  # games per part; GAMES=1 with 25 pairs gives a 50-game batch (seat A is on the play in each game 0)
RUN=$1; D=$2; SEED=$3; TAG=$4; shift 4
specs=""; p=0; i=0
for pair in "$@"; do
  a=${pair%/*}; b=${pair#*/}
  # SEATINGS=1 (env): one part per pair, for runs with no variant to swap (list a/b and b/a to swap who is on the play)
  for planseat in $([ "${SEATINGS:-2}" = 1 ] && echo a || echo a b); do
    p=$((p+1))
    # PARTS (env): only these part numbers, e.g. to finish a batch whose machine went away; same seeds and decks
    if [ -z "$PARTS" ] || [[ " $PARTS " == *" $p "* ]]; then i=$((i+1)); specs="$specs $p:$a:$b:$planseat:$i"; fi
  done
done
run_part() {
  IFS=: read p a b s i <<< "$1"
  [ $i -le 6 ] && sleep $(( (i-1) * 5 ))  # stagger the first JVM boots (shared card database lock)
  o=$([ $s = a ] && echo b || echo a)
  F=""; for v in $VARIANT; do F="$F --${v%%=*}-$s"; [[ $v == *=* ]] && F="$F ${v#*=}"; done
  for v in $BOTH; do for t in $s $o; do F="$F --${v%%=*}-$t"; [[ $v == *=* ]] && F="$F ${v#*=}"; done; done
  python3 play/match.py --runtime /root/xmage/xmage/mage-server --classes /tmp/xmage-cls --a claude --b claude \
    --deck-a $D/$a.dck --deck-b $D/$b.dck $F --games $GAMES --seed $((SEED+p)) --model claude-opus-5-5 --effort high \
    --out $RUN/part$(printf %02d $p) > /tmp/claude-0/${TAG}_$p.out 2>&1
  echo "DONE $?" >> /tmp/claude-0/${TAG}_$p.out
}
export -f run_part; export RUN D SEED TAG VARIANT BOTH GAMES
echo $specs | tr ' ' '\n' | xargs -P 6 -I{} bash -c 'run_part {}; sleep 2'
echo "BATCH DONE" > /tmp/claude-0/${TAG}_batch.done
