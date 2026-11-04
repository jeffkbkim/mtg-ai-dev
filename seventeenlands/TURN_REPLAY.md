# Replaying 17lands games in XMage

`turn_replay.py` replays 17lands DSK games in XMage turn by turn and measures how often each turn reproduces the
recorded end of turn. The aim is labelled decisions for every turn: the recorded ones (exact) plus the ones the
record leaves out, filled in by search (inferred). It's our own design; DraftZero's write-up (docs/008 in their
repo) was read for lessons, not code.

## How it works

- **Seats.** Both seats are `ReplaySeat`s (`engine/xmage/ReplaySeat.java`, run by `ReplayMatch.java`), scripted
  from Python over one socket.
- **Decks and draws.** The user's deck is recorded. The opponent's deck is the cards it revealed, plus basics.
  - Each seat draws from a queue: the user its recorded hands and draws, the opponent the cards it needs next.
  - Cards it must still draw are kept away from the top of the library, so mill and manifest effects don't eat them.
- **Each turn**, both seats make their recorded plays: lands, spells, activated abilities, attacks, blocks.
  - The record doesn't say when each play happened, the targets, who blocked whom, modes, "may" answers, trigger
    order, or whether a Room door was unlocked. Each of these is a **choice point**, likeliest alternative first.
  - In the end step the true state is compared with the record: both life totals, the user's hand, the opponent's
    hand size, both boards, and every recorded play happened.
  - If it doesn't match, XMage rewinds to the start of the turn (its own rollback). Then other choices are tried,
    fewest departures from the likeliest first, up to 40 attempts.
- **After a turn no attempt reproduces**, the visible state is reset to the record:
  - life, hands, boards, tokens (by class), face-down cards (manifested) and Auras (attached by a heuristic), with
    cards moved directly between zones;
  - then the game goes on.
  - Turns after a reset start from a less exact state: tapped state, counters and door states aren't reset.
- **Runs are reproducible.** XMage's random numbers are seeded per game and per turn, and every choice order is
  independent of XMage's object ids.

```sh
uv run --group data python seventeenlands/turn_replay.py --games 300 --seed 7 --run m300   # ~27 min on the mini
```

Output in `~/mtg-data/17lands/DSK/turn_replay/<run>/`:
- `turns.jsonl`: one line per turn, with the choices taken, the attempts and what differed.
- `summary.json`: the totals.

## Results, 2026-10-23 (300 random games, seed 7, main `f3222cf`)

95% intervals in brackets.

| Turns | Reproduced |
|---|---:|
| All, n = 5,158 | **70.2%** (69.0–71.5) |
| Before a game's first miss ("clean"), n = 2,614 | **88.9%** (87.7–90.1) |
| After a reset, n = 2,544 | 51.0% (49.0–52.9) |
| After a reset that matched the record exactly, n = 2,332 | 55.5% (53.5–57.5) |

- **By player turn:** 98% on turn 1, 97% on 2, 89% on 3, 76% on 4, 70% on 5, 57% on 6, 53% on 7, 42% on 8 and later.
- **Whole games:** 11 of 300 games reproduce every turn.
- **Attempts:** 84% of reproduced turns match on the first attempt.
- **Resets:** 84% of resets match the recorded visible state exactly.
- **Activated abilities:** turns with one reproduce 37% of the time.

**Why clean turns miss** (289 misses):

| Cause | Misses |
|---|---:|
| Every recorded play happened, but the end state differs | 225 |
| A recorded play was never possible | 36 |
| A recorded play was possible but never happened in a way that matched | 28 |

The state differences are mostly on the user's board (68), the opponent's board (38) and the user's hand (29). The
plays that were never possible are mostly the opponent's spells (15).

**After a reset** the same causes appear, more often. A reset can't restore what 17lands doesn't record (tapped
lands, counters, which Room doors are unlocked, what an Aura enchants), and those differences change later turns.

## Update, 2026-10-23 evening: better resets (same 300 games, seed 7)

What changed:
- **Room doors.** The replay casts the exact door 17lands recorded. A reset restores each Room's unlocked doors:
  the doors cast, plus the doors whose "when you unlock this door" trigger appears in the record.
- **Tapped state.** A reset taps as many of the active player's lands as it spent mana (basics first), plus its
  attackers. Those stay tapped through the other player's turn.
- **Searches and manifests** pick the card the seat still lacks compared with its recorded end of turn.
- **A game's final turn** is counted apart. The record often ends in a concession, which no play reproduces;
  49 of 177 final turns reproduce.

| Turns, final turns excluded | Before | After |
|---|---:|---:|
| All | 70.2%* | **73.3%** (72.1–74.5), n = 5,000 |
| Clean | 88.9% | **89.9%** (88.7–90.9), n = 2,733 |
| After a reset | 51.0% | **53.4%** (51.3–55.4), n = 2,267 |

\* Before, final turns were counted with the rest.

- **By player turn:** 99%, 97%, 90%, 79%, 72%, 63%, 55%, then 45% on turn 8 and later.
- **Whole games:** 23 of 300 reproduce every non-final turn.
- **Right after a reset** is the weakest turn: 47% reproduce, against 78% two turns later. What a reset still can't
  restore is mostly what 17lands never records: +1/+1 and other counters, what an Aura or Equipment is attached to,
  the graveyard (which delirium counts), and an Overlord cast for its impending cost. Turns off by one or two life
  are the common symptom.

## Ambiguity check, 2026-10-23 (100 games, seed 7, `--probe 30`)

How it works: after a clean turn reproduces, every other alternative at each of its choice points is tried, one
at a time. Everything before that point keeps the reproducing choices; everything after takes the likeliest
alternative. If another alternative also reproduces the turn, the record can't tell them apart, so that searched
label is **ambiguous**.

- 834 turns were probed, and every alternative of every choice point was tried.
- The reproducing choices replayed to the same end in 833 of 834.

| Searched choice | Choice points | Ambiguous |
|---|---:|---:|
| User: when to make a play on its own turn (now or later, so before/after combat and order) | 750 | 81.5% |
| User: targets | 144 | 47.2% |
| User: when to cast on the opponent's turn | 105 | 27.6% |
| User: "may" answers | 19 | 68% |
| User: trigger order | 16 | 88% |
| Opponent: when to play on its own turn | 770 | 82.2% |
| Opponent: targets | 173 | 61.3% |
| Block pairing | 1 | 0% |

- Of the 445 turns with at least one user choice point, all of them were unique in only 46 (10%).
- Of the 111 turns with user targets, all targets were unique in 54 (49%).

What this means for training labels:
- **Use the recorded sets:** which lands and spells were played, attacks, blocks, mulligans.
- **Don't train on order or timing within a turn.** The record almost never pins them down. Usually the order
  doesn't change the end state, which is exactly why it can't be recovered.
- **Use a target only when the check finds it unique** (about half the time). The per-choice-point result is in
  `turns.jsonl` (`ambiguity`).
- Block pairing is almost never a choice: 17lands' blockers and blocked attackers pin it down.

## Training rows, 2026-10-24 (`--rows`)

`--rows` writes `decisions.jsonl.gz`, one row per decision of the user's seat. Rows come only from clean turns
that reproduced, excluding final turns, plus the mulligans.

- **Fields:**
  - what the seat saw: `obs`, the same per-seat observation the Claude player and the encoder use, with no hidden
    cards;
  - `options` and `choice`;
  - `game`, `draft_id` (for the frozen split), `turn`, `kind` and `step`.
- **`label`** says how sure the choice is:
  - `recorded`: the record decides it. Attacks, blocks, mulligans, and windows where the only reading of the record
    is to pass or play.
  - `unique`: a searched choice the ambiguity check proved was the only one that fits.
  - `ambiguous`: a searched choice where other alternatives fit too.
  - `unprobed`: searched, without an ambiguity check (when run without `--probe`).
  - `not_recorded`: an answer the replay fixes itself (surveil and scry keep the top card).

On 100 games (seed 11, `--probe 30`) there were 9,045 rows: 8,066 recorded, 266 unique and 713 ambiguous.

| Kind | recorded | unique | ambiguous |
|---|---:|---:|---:|
| Priority | 6,712 | 173 | 639 |
| Attack | 740 | 0 | 0 |
| Block | 51 | 0 | 0 |
| Target | 18 | 45 | 30 |
| Other choices (search, manifest, modes, "may", trigger order) | 545 | 48 | 44 |

- **Most recorded priority rows are passes.**
- **Of the 717 priority rows that make a play** (cast, land, ability), 588 are ambiguous, because which window a
  play happened in usually can't be told.
- So the record pins down *which* plays a turn made, not *when* each was made. How to turn that into a training
  target is a model decision, left open here.

## How to read these numbers

- **The opponent's side uses hindsight.** It holds exactly the cards it plays, when it plays them. So a reproduced
  turn shows the user's recorded plays can be realised in XMage, not that the opponent's hidden hand is known.
- **A guess can match by luck.** A searched choice that reproduces the end state is likely, not certain.
  Labels from searched choice points are inferred and must be kept apart from the recorded ones.
- **Compared with DraftZero.** They report 89% of Foundations turns reproduced.
  - They rebuild every turn's start from the record, inferring tapped state and counters, with the same opponent
    hindsight. That's closest to our clean rate (88.9%).
  - Our chained replay pays for every earlier miss.

## Next

1. Better resets: infer tapped lands from mana spent and attacks, Room door states, counters. That moves the
   after-reset rate toward the clean rate.
2. The opponent's plays that were never possible (its hand or mana after a reset).
3. Activated abilities (37%): match more 17lands ability ids to XMage options, and try their timing.
4. Label output: the per-decision rows (options, choice, exact or inferred) for training.

## Quality batch, 2026-10-28 (1,500 games, seeds 2001/2002/2004, `--probe 30 --rows`, main `4966286`)

Four workers of 500 games were started on the mini; the seed-2003 worker died at start (JVM socket timeout), and the
four-worker start caused a WindowServer hang and logout on the mini: the crash report shows each Python process at about 13 GB while loading the replay parquet (about 53 GB on a 16 GB machine). Fix the loading before running it on the mini again.

| Turns | Reproduced |
|---|---:|
| From an exact start, n = 23,357 | 75.8% |
| Before a game's first miss ("clean"), n = 13,050 | 89.3% |
| After a reset, n = 11,399 | 53.1% |
| Final turns, n = 956 | 24.2% |

Decision rows (user seat, clean reproduced turns): 129,610, about 86 per game. Recorded 115,816 (89.4%), unique
3,881 (3.0%), ambiguous 9,582 (7.4%), not recorded 331 (0.3%).

Speed: about 8.3 s per game per worker with three workers running, so about 21 games a minute in total. At two workers
the full 1.01M games would take roughly seven weeks on the mini.

## Memory fix, 2026-10-29

The ~13 GB per process came from picking the sample: `with_row_index().filter(is_in(...))` can't be pushed into the
parquet reader, so polars decoded every column of the file (2,509 columns, 13 row groups of ~82k games). Reading in
windows, one slice per game, the streaming engine and smaller row groups all still peaked at 7-9 GB, and the process
kept ~5 GB afterwards. The sample is now picked in a short-lived child process that writes `sample.parquet` to the run
directory and exits, under a lock so only one worker picks at a time. Measured: peak 6.8 GB in the child for ~7 s,
74 MB in the parent afterwards (500 games, seed 2001).

## 50k-game run, 2026-10-29 to 31 (seed 5001, `--probe 30 --rows`, code `0de201a`)

`replay_batches.py --name dsk50k --sample 50000 --seed 5001 --batch 500 --workers 3`, on the mini. 100 batches of 500,
about 68 minutes each, 41 hours in all. 4 batches failed when two workers started XMage at the same moment and one
couldn't open XMage's card database (`expansionDao` null, then a socket timeout); they were rerun and all 100 finished.
Free memory never went below 48%, swap stayed flat.

| Turns | Reproduced |
|---|---:|
| From an exact start, n = 787,264 | 76.2% |
| Before a game's first miss ("clean"), n = 441,428 | 89.5% |
| After a reset, n = 380,135 | 54.0% |
| Final turns, n = 31,684 | 24.2% |

Decision rows: 4,456,698 (about 89 per game, 0.75 GB gzipped, `dsk50k/b*/decisions.jsonl.gz`). Recorded 3,979,567
(89.3%), unique 133,258 (3.0%), ambiguous 332,472 (7.5%), not recorded 11,401 (0.3%).

Since then (2026-10-31) an engine that exits before connecting is started again, up to 3 tries, a few seconds apart.

## Second 50k-game run, 2026-10-31 to 2026-11-03 (seed 5002, `--probe 30 --rows`, code `0de201a`+, classes from `77067d0`)

`replay_batches.py --name dsk50k-2 --sample 50000 --seed 5002 ... --exclude dsk50k/rows_done.txt`: 50,000 games not in
the first run. One game (row 499338) looped in Python on its turn 22 and held its batch for 41 hours; the `--stall`
watchdog was added for it (that game is now given up after 10 minutes), and the run resumed with a shared queue. In
all, 49,999 games finished (1 stall). Free memory never went below 43%.

| Turns | Reproduced |
|---|---:|
| From an exact start, n = 786,287 | 76.2% |
| Before a game's first miss ("clean"), n = 439,844 | 89.4% |
| After a reset, n = 380,563 | 54.2% |
| Final turns, n = 31,438 | 24.0% |

Decision rows: 4,438,971 (0.74 GB gzipped, `dsk50k-2/b*/decisions.jsonl.gz`). Recorded 3,962,673 (89.3%), unique
132,770 (3.0%), ambiguous 332,098 (7.5%), not recorded 11,430 (0.3%). With the first run: 99,999 games, 8.9M rows.
Still open: why row 499338 loops.

## Correction, 2026-11-03: filler rows (both 50k runs and the 1,500-game batch)

Found by the Model Arch thread. Once a game passed its last recorded turn, XMage kept playing (the real ending,
usually a concession, isn't reproduced), every answer was a default (pass, no attack, option 0), and each of those
decisions was written as a `recorded` row with turn 0. The code assumed rows without a turn script only happen before
turn 1. So the row counts and label shares above are inflated. In `b0000` of each run:

| | dsk50k b0000 | dsk50k-2 b0000 |
|---|---:|---:|
| All rows | 46,569 | 46,892 |
| Filler (turn 0, not a mulligan or bottom) | 36,230 (78%) | 36,368 (78%) |
| Real rows | 10,339 | 10,524 |
| of which recorded / unique / ambiguous / not recorded | 55% / 12% / 32% / 1% | 54% / 12% / 33% / 1% |

So about 21 real rows per game, roughly 2.1M across the 100k games (estimated from these two chunks), and about two
thirds of them are recorded or unique. Drop filler with: turn 0 and the prompt is not a mulligan or a bottom. The turn
reproduction rates are unaffected. The 30-turn cap drops nothing: `num_turns` is at most 30 in the DSK file.

Fixed in `turn_replay.py`: rows past the record are no longer written; they are counted as `decisions_past_record`.
Ending the game once the record runs out: done, see below.

Also fixed (2026-11-04): once the record runs out after turn 1, Python replies `{"concede": <the 17lands loser>}` and
`ReplaySeat` concedes that seat at its next priority, so the game ends the way the record did instead of being played
out. Needs the engine classes rebuilt from this commit (`~/mtg-data/xmage-cls-replay`, the `replay_batches.py`
default, is rebuilt). On 6 games: the same 160 real rows, 0 decisions past the record (was 29).

## The 41-hour loop, found 2026-11-04

Row 499338 records 14 blockers on 14 blocked attackers in one turn. `block_pairings` walked every assignment of
blockers to attackers in order (14**14) looking for ones that cover every attacker, and the first such assignment is
about 10**13 steps in. The walk now stops after 20,000 assignments and, if it found none, builds one covering pairing
directly; small cases are unchanged. The game now replays in 28 seconds. The `--stall` watchdog stays as a backstop.
Big combats (2026-11-04): when there are too many assignments to search (0.14% of 17lands turns with blocks, measured
on 100k games), the first block decision now ranks pairings with `combat_pairing`: using the creatures' power and
toughness at the block, it picks the pairing (moving or swapping one blocker at a time) whose predicted combat deaths
best match the recorded ones, and tries that first.
