# Claude plays DSK

Lets a Claude model play Duskmourn games through our XMage seat, against the random bot or another Claude,
and records every decision. Purpose: measure how well Claude plays, what it costs, and whether its games are worth
using as extra training data or as an opponent.

- `match.py`: runs N games with both seats driven from Python (`engine/xmage/TwoSeatMatch.java`). Each seat has its own
  socket and its own player, so a player only ever sees its own seat's view (the hidden-info-checked observation).
- `players.py`: `RandomPlayer` (same policy as `engine/xmage/run_games.py`) and `ClaudePlayer`: headless Claude Code
  (`claude -p`, stream-json, no tools), one conversation per seat per game so it remembers the game. Replies are one
  JSON line `{"choice": n, "reason": "..."}`; an invalid reply gets one retry, then option 0 is played and the decision
  is flagged `invalid`.
- `render.py`: observation and options as text. Card rules text is shown the first time a seat sees a card
  (`engine/vocab/dsk_card_text.json`, dumped from XMage by `engine/xmage/CardTextDump.java`).
- `primer/`: what the Claude player is told about the format: `dsk_meta.md` (mechanics, archetypes, strong commons, with
  sources), a 17lands games-in-hand win rate per card (`dsk_17lands_stats.json`, computed by `card_stats_17lands.py`
  from the public DSK Premier Draft game data), and its own decklist with card text. It is not told the opponent's deck.
- `summarize.py`: results, and per decision / per game time, tokens and cost.

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

- Claude sees the state at each decision, not a log of what happened between decisions.
- Mulligans, mana payment, X values and damage assignment use XMage's built-in defaults (counted as FALLBACK in the log).
- Costs in the summary are API list-price equivalents reported by Claude Code; on a subscription the run counts
  against plan usage instead.
