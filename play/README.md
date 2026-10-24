# Claude plays DSK

Lets a Claude model play Duskmourn games through our XMage seat, against the random bot or another Claude,
and records every decision. Purpose: measure how well Claude plays, what it costs, and whether its games are worth
using as extra training data or as an opponent.

- `match.py`: runs N games with both seats driven from Python (`engine/xmage/TwoSeatMatch.java`). Each seat has its own
  socket and its own player, so a player only ever sees its own seat's view (the hidden-info-checked observation).
- `players.py`: `RandomPlayer` (same policy as `engine/xmage/run_games.py`) and `ClaudePlayer`: headless Claude Code
  (`claude -p`, stream-json, no tools). The conversation restarts at the start of each of the seat's own turns with a
  log of the game so far. Replies are one JSON line `{"choice": n, "reason": "..."}`, optionally with `"pass_until"`
  (`my_main`, `end_of_turn` or `my_turn`) to skip empty priority windows (never its own main phases, combat or
  anything on the stack); the prompt asks for one on every PASS that isn't followed by an action at the next window; an invalid reply gets one retry, then option 0 is played and
  the decision is flagged `invalid`.
- `render.py`: observation and options as text. Card rules text is shown the first time a seat sees a card
  (`engine/vocab/dsk_card_text.json`, dumped from XMage by `engine/xmage/CardTextDump.java`).
- `primer/`: what the Claude player is told about the format: `dsk_meta.md` (mechanics, archetypes, strong commons, with
  sources), a 17lands games-in-hand win rate per card (`dsk_17lands_stats.json`, computed by `card_stats_17lands.py`
  from the public DSK Premier Draft game data), and its own decklist with card text. It is not told the opponent's deck.
  `lessons_v*.md` are optional card-agnostic play habits drawn from reviewed games, added per seat with
  `--lessons-a` / `--lessons-b`. The player name in each record carries the lessons version and each decision the
  system prompt's hash (`prompt_sha`), so games from different prompts are never pooled by accident.
  Primer v2 (`--primer v2`, or `PRIMER=v2`; v1 is the default; names gain `:primer2`): `dsk_meta_v2.md` (per-pair
  plans, synergies, key cards, rares, how to beat each pair; mandatory attack/block/tap-out/mulligan checks;
  instant-speed cards to respect per color; no win rates, 17lands data only picked the cards, via
  `archetype_stats_17lands.py`) instead of `dsk_meta.md` + the GIH table, and each deck card gets a one-line role
  from `dsk_card_roles.json` (written by `card_roles.py`: rules from card text plus hand corrections).
- `--plan-a` / `--plan-b` make a Claude seat keep a plan (role, win condition, race, opponent read, this turn, next
  turn) that it rewrites in every reply; the latest plan is shown in each prompt and recorded with each decision.
- `--facts-a` / `--facts-b` add a "Facts:" block to each decision (`facts.py`), computed from the seat's own
  observation: untapped mana and that lands untap only in the seat's own untap step, which creatures can block on the
  opponent's next turn (attackers stay tapped), the least damage that gets through if everything attacks and the
  defender blocks as well as possible (both directions), and how each possible single or double block, or each
  attacker, ends with no tricks. Aimed at the reviewer's most common flags (rules timing and combat arithmetic).
- `--check-a` / `--check-b` give a second look: after the first attack or block declaration of a combat, and after
  any non-PASS choice while either player is at 8 life or less, the player is asked (same conversation) for the
  opponent's best answer and a final choice. Each such decision records `self_check` (first choice, whether it
  changed); about 19% of model decisions in the plan-pairs batches would have been checked.
- `summarize.py`: results, and per decision / per game time, tokens and cost.
- `deck_pool.py`: builds real drafted decks from 17lands game data (`engine/xmage/decks/17lands/`, `17lands-r2/`).
- `ab_report.py`: compares player variants (e.g. lessons on vs off) across runs: wins with a 95% interval, per
  deck, and behaviour numbers a lesson might move (decking losses, attacks per turn, lands left untapped, cost).
- `launch_pairs.sh`: runs variant-vs-baseline deck pairs (each pair twice, the variant on seat A then on seat B, GAMES
  games each), 6 parts at a time, e.g. `play/launch_pairs.sh <out> engine/xmage/decks/17lands-r2 600 b03 trophy_10/trophy_11 ...`.
  VARIANT names the variant seat's flags (`VARIANT="facts check"`, or `VARIANT="effort=medium"` for `--effort-a medium`);
  BOTH gives flags to both seats. `--effort-a` / `--effort-b` set one Claude seat's effort, overriding `--effort`.
- `review.py`: a reviewer (`claude -p`, no tools) reads each seat's game as that seat saw it and flags clear errors
  ("blunder" or "mistake", judged only on what was visible then, with a category: rules, combat_math, crack_back,
  hidden_info or other) plus suspected engine or harness bugs. Flags go to
  `<game>.review-<seat>.json` next to the game; nothing is deleted, so filtering is chosen when building a training
  set. Reviews about half the games by default (`--fraction 0.5`, a stable hash of each game's path, so reruns pick
  the same games). `--summary` prints flag rates per player variant, by category per 1,000 decisions. About $0.52 per
  seat-game at Opus high.

## Run

Build the Java classes as in `engine/xmage/README.md` (now including `TwoSeatMatch.java`), then:

```sh
python3 play/match.py --runtime ~/xmage/xmage/mage-server --classes /tmp/xmage-cls \
    --a claude --b random --deck-a engine/xmage/decks/dsk_ug.dck --deck-b engine/xmage/decks/dsk_uw.dck \
    --games 5 --out /mnt/project-files/claude-games/<run>
python3 play/summarize.py /mnt/project-files/claude-games/<run>
```

`--a claude --b claude` plays Claude against Claude (two separate processes). `--model` and `--effort` pick the model.

## Recording

`<run>/game<N>.jsonl` has one line per real decision for both seats: observation, options, choice, and for Claude
seats the exact prompt text, the reply, a one-line reason, tokens (`usage` per model turn), cost and seconds.
`<run>/games.jsonl` has one line per game; `<run>/config.json` the settings and code commit; `<run>/jvm.log` the
engine's own log (leaks, rejected moves, fallbacks).

`python3 play/manifest.py` rebuilds `<recordings>/manifest.jsonl`, one line per finished game with a verdict:
`unusable` (a seat-version bug that corrupts every game, or an unfinished game), `suspect` (XMage decided something
for the player, a reviewer bug note that changed the board, or the pre-payer seat), `clean`. `cautions` lists weaker
signals (a buggy card that appeared, moves offered then refused or rolled back, repeated prompts); `flags` lists the reviewer's player errors; `reviewed` says whether both
seats were reviewed. It is a view over config.json, jvm.log and the review files, rebuilt from scratch each run; what
to filter on is decided when building a training set.

## Known limits

- Mana is paid automatically by the seat (lands before creatures, keeping the colours the hand needs). X (the
  largest affordable), combat damage among several blockers and "distribute" amounts (TARGET_AMOUNT, e.g. Omnivorous
  Flytrap's counters, targets included) are XMage AI choices, not asked (counted as FALLBACK in the log).
- Costs in the summary are API list-price equivalents reported by Claude Code; on a subscription the run counts
  against plan usage instead.
