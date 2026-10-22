# Claude plays DSK

Lets a Claude model play Duskmourn games through our XMage seat, against the random bot or another Claude,
and records every decision. Purpose: measure how well Claude plays, what it costs, and whether its games are worth
using as extra training data or as an opponent.

- `match.py`: runs N games with both seats driven from Python (`engine/xmage/TwoSeatMatch.java`). Each seat has its own
  socket and its own player, so a player only ever sees its own seat's view (the hidden-info-checked observation).
- `players.py`: `RandomPlayer` (same policy as `engine/xmage/run_games.py`) and `ClaudePlayer`: headless Claude Code
  (`claude -p`, stream-json, no tools). The conversation restarts at the start of each of the seat's own turns with a
  log of the game so far. Replies are one JSON line `{"choice": n, "reason": "..."}`, optionally with `"pass_until"` to
  skip empty priority windows (never its own main phases); an invalid reply gets one retry, then option 0 is played and
  the decision is flagged `invalid`.
- `render.py`: observation and options as text. Card rules text is shown the first time a seat sees a card
  (`engine/vocab/dsk_card_text.json`, dumped from XMage by `engine/xmage/CardTextDump.java`).
- `primer/`: what the Claude player is told about the format: `dsk_meta.md` (mechanics, archetypes, strong commons, with
  sources), a 17lands games-in-hand win rate per card (`dsk_17lands_stats.json`, computed by `card_stats_17lands.py`
  from the public DSK Premier Draft game data), and its own decklist with card text. It is not told the opponent's deck.
  `lessons_v*.md` are optional card-agnostic play habits drawn from reviewed games, added per seat with
  `--lessons-a` / `--lessons-b`. The player name in each record carries the lessons version and each decision the
  system prompt's hash (`prompt_sha`), so games from different prompts are never pooled by accident.
- `--plan-a` / `--plan-b` make a Claude seat keep a plan (role, win condition, race, opponent read, this turn, next
  turn) that it rewrites in every reply; the latest plan is shown in each prompt and recorded with each decision.
- `summarize.py`: results, and per decision / per game time, tokens and cost.
- `deck_pool.py`: builds real drafted decks from 17lands game data (`engine/xmage/decks/17lands/`, `17lands-r2/`).
- `ab_report.py`: compares player variants (e.g. lessons on vs off) across runs: wins with a 95% interval, per
  deck, and behaviour numbers a lesson might move (decking losses, attacks per turn, lands left untapped, cost).
- `launch_pairs.sh`: runs plan-vs-no-plan deck pairs (each pair twice, the plan on seat A then on seat B, 2 games each),
  6 parts at a time, e.g. `play/launch_pairs.sh <out> engine/xmage/decks/17lands-r2 600 b03 trophy_10/trophy_11 ...`.
- `review.py`: a reviewer (`claude -p`, no tools) reads each seat's game as that seat saw it and flags clear errors
  ("blunder" or "mistake", judged only on what was visible then) plus suspected engine or harness bugs. Flags go to
  `<game>.review-<seat>.json` next to the game; nothing is deleted, so filtering is chosen when building a training
  set. `--summary` prints flag rates per player variant. About $0.80 per seat-game at Opus high.

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

## Known limits

- Mana payment, X values and damage assignment use XMage's built-in defaults (counted as FALLBACK in the log).
- Costs in the summary are API list-price equivalents reported by Claude Code; on a subscription the run counts
  against plan usage instead.
