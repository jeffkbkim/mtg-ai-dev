# DSK card coverage soak

Plays many games through XMage with decks that rotate through every DSK card, to find cards that break:
JVM exceptions, hangs, games that never finish, rejected moves, unmapped abilities or choices, and
hidden-information leaks caught by the seat's checker. Our seat plays the biased-random policy from
`engine/xmage/run_games.py`; the other seat is XMage's own AI, so cards on both sides get played.

- `DskNumbers.java`: writes `dsk_numbers.json` (DSK collector number per card name) so decks can be written as `.dck`.
- `soak.py`: builds two-colour decks (plus decks for the three- and five-colour cards), least-used cards first,
  and runs `SeatSpike` on pairs of them in parallel JVMs. One directory per run with both decks, `jvm.log`,
  `decisions.jsonl.gz` and `run.json`.
- `report.py`: per-card exposure and problems (`cards.json`, `report.md`).

A card with no problems that never reached the battlefield or stack is listed as untested, not as fine.
Problems that name no card (a hang, a token's unmapped ability) are listed per run with both decks, and the
report ranks the cards that show up most often in those runs.

```sh
# build the seat classes first (engine/xmage/README.md), then:
uv run python experiments/coverage_soak/soak.py --runs 600 --games 4 --jobs 4 --out ~/mtg-data/soak/<name>
uv run python experiments/coverage_soak/report.py ~/mtg-data/soak/<name>
```

Output stays outside Git. `config.json` in the output records the arguments, seed and commit.
