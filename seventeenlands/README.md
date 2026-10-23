# 17lands DSK data

Public 17lands datasets for Duskmourn Premier Draft (game, draft and replay data), downloaded on the Mac mini to
`~/mtg-data/17lands/DSK` by `scripts/download_17lands.sh`, outside Git. Checksums: `SHA256SUMS` in that folder.

- `prepare.py convert`: csv.gz to Parquet (`parquet/`, about 300 MB).
- `prepare.py audit`: row counts, duplicate keys, missing values, card names against XMage's DSK list, deck sizes,
  and whether games, replays and drafts line up. Writes `audit.json`.
- `prepare.py split`: freezes `splits.parquet` (draft_id to train/validation/test) and `splits.json`.
- `replay_check.py`: how much of a replay is an exact record of the player's decisions. Writes `replay_check.json`.

## Audit, 2026-10-22

| | rows | drafts |
|---|---:|---:|
| game data | 1,011,949 games | 173,545 |
| replay data | 1,011,949 games | 173,545 |
| draft data | 7,082,745 picks | 169,666 |

Games played 2024-09-24 to 2024-10-28. No duplicate keys. Every game has a replay and every replay a game.
Every deck has 40 to 61 cards. 2,363 drafts have picks but no games, and 6,242 games' drafts have no pick data.
Rank is missing for 5,163 games and 483,690 picks; splash colours are mostly empty (no splash).

**Cards:** 17lands lists 286 cards and XMage's DSK list 276. The 10 extra are Duskmourn's Special Guests (Collected
Company, Damnation, Expropriate, Hallowed Haunting, Maddening Hex, Noxious Revival, Phantasmal Image, Sacrifice,
Soul Warden, Unholy Heat). XMage implements all 10 under set SPG, so no card is unsupported. 20,928 games (2.1%)
have a Special Guest in the deck. **2026-10-23:** they're now in our card list (`engine/xmage/DskCards.java`), so the
vocabulary and card text have 286 cards (card and ability ids shifted; no model had been trained on the old ones).
XMage's own DSK boosters don't contain Special Guests, so a faithful draft needs our own pack generator.

**Split** (`splits.json`): by draft, `sha256("mtg-ai-dsk-split-v1:" + draft_id)`, 80/10/10. Every row of a draft,
in all three datasets, lands in the same split. 140,619 / 17,731 / 17,558 drafts; games 809,318 / 102,031 / 100,600.
17lands records one player's side per game, and opponents are anonymous, so two recordings of the same game can't be
paired. If both players logged a game, the two rows may land in different splits.

## Replay check, 2026-10-22 (20,000 random games, seed 0)

| Decision | What the replay records | Measured |
|---|---|---|
| Mulligan | every candidate hand | exact in 100% of games |
| Land drop | which land | exact |
| Attack | which creatures attacked | exact |
| Spells on your turn | which cards, not order, timing within the turn, or targets | 15.1% of turns have 2+ spells (order unknown); 37.5% of spells have "target" in their text (target unknown) |
| Blocks | which creatures blocked, not what each blocked | 57.0% of block turns face 2+ attackers (assignment unknown) |
| Cards in hand | end-of-turn hand | rebuilt hand matches the record on 94.6% of your turns and 91.3% of opponent turns; whole game in 26.6% of games |

Why the rebuilt hand drifts (most common unrecorded moves): permanents with flash cast on the opponent's turn
(Floodpits Drowner, Appendage Amalgam, Growing Dread, Fear of Impostors); the replay only lists instants and
sorceries there. Also cards returning to hand (Fear of Infinity, bounce) and basic lands moving without a record. After a
mismatch the check resyncs on the recorded hand, so each turn's starting hand is known even when a move in
between isn't.

So the exact, ready-to-use labels are mulligans, land drops and attack sets. Spell choices are exact as sets but
need order, timing and targets inferred, and block assignments need inferring in over half of block turns. Any
training data built from replays should mark which parts are exact and which are inferred.

## Decision tables, 2026-10-23

`decisions.py` writes one row per decision for the three kinds a replay records exactly, from all 1,011,949 games,
to `~/mtg-data/17lands/DSK/decisions/` (440 MB). Every row has its draft's split; none is missing one.

| Table | Rows | Label | Context that may be off (flagged) |
|---|---:|---|---|
| `mulligans.parquet` | 1,132,220 | keep or mulligan; for a kept hand after mulligans, the cards put on the bottom | none: every hand seen is recorded, and the bottomed cards always account for the difference |
| `land_drops.parquet` | 7,185,684 | which land was played (or none, 9% of rows) | `hand_start` = last recorded hand + this turn's draws; the played land was in it 98.6% of the time (`land_in_hand_start`) |
| `attacks.parquet` | 6,073,790 | which creatures attacked, and which were blocked | `attackers_available` = creatures at the end of the previous turn; misses haste creatures cast this turn and animated lands, so every attacker was in it 93.7% of the time (`attackers_in_available`) |

Every table also has the game's key, `on_play`, `won`, `rank`, `num_mulligans`, `has_special_guest`, and (for land
drops and attacks) both players' life, lands, creatures and other permanents at the end of the previous turn, plus
the opponent's hand size. Cards are names; nothing is encoded. How to turn these into model inputs is a model
decision, left open here.

## Fully replayable games, 2026-10-23 (`replayable.py`, 20,000 games)

A game counts as replayable move for move only if nothing about either player's moves has to be guessed.
**2 of 20,000 games (0.0%) pass.** Share of games failing each test (a game can fail several):

| Test | What can't be told from the replay | Games failing |
|---|---|---:|
| targets | any spell or ability with a target | 99.3% |
| timing | the active player cast something and attacked in the same turn (before or after combat?) | 99.5% |
| order | one player made 2+ plays in a turn (the "abilities" columns include triggers, so this test is strict) | 99.7% |
| hand | the rebuilt hand drifted from the recorded one at some point | 73.4% |
| blocks | 2+ attackers met blockers (who blocked whom?) | 72.2% |
| guests | a Special Guest in the deck (now supported) | 2.1% |

So no game can be replayed as is. To replay games in XMage, the missing parts (targets, order, timing, block
assignments) have to be filled in by search: try the choices the engine allows and keep the ones that lead to the
next recorded end-of-turn state. Those filled-in choices are inferred labels, not recorded ones.
