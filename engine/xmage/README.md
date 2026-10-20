# XMage seat

A Java player class that sits in a seat of a real XMage game and hands every decision to Python.
Built against the **unmodified XMage 1.4.62 release jars** (build option 1); nothing in XMage is patched.

- `PySeat.java`: the seat. Subclasses XMage's `ComputerPlayer`, sends each real decision as one JSON line
  over a localhost socket and plays the option Python picks. Forced decisions (only one legal option) are
  answered in Java. Rejected moves and unmapped abilities are logged, never hidden.
- `Observer.java`: builds the observation from XMage's per-seat view (`GameView`, what a human client sees),
  entries in contract order `[global | cards | stack abilities]`, plus edges. Checks every message against the
  full game state for hidden-information leaks.
- `AbilityKeys.java`: stable ability keys `"<card name>#<i>"` (printed) and `"<card name>#g<i>"` (granted to
  another object or put on a token), and named choices: `alt_cost:none` / `alt_cost:ImpendingAbility` for an
  alternative-cost prompt, `"<card name>#mode<i>"` for a mode of a modal card (printed order), `choice:<text>`
  for other named prompts.
- `VocabDump.java`: writes `engine/vocab/dsk_vocab.json` (276 DSK card names, ability keys and texts, named choices).
- `SeatSpike.java`: runs N games, our seat vs XMage's AI.
- `TwoSeatMatch.java`: runs N games with both seats driven from Python (used by `play/match.py`).
- `CardTextDump.java`: writes `engine/vocab/dsk_card_text.json` (rules text of every DSK card as XMage implements it).
- `run_games.py`: Python side, a random-move bot that records every decision to JSON lines.
- `decks/`: smoke-test decks; `dsk_ug_modal.dck` swaps in modal spells to exercise MODE prompts.

Decision format and the leak checks: `/mnt/project-files/notes/xmage-step3-observation.md`.
Turning the JSON lines into batch tensors: `engine/encode.py`.

## Build and run

Needs Java 21 and the release zip:

```sh
mkdir -p ~/xmage && cd ~/xmage
curl -sSL -o mage.zip https://github.com/magefree/mage/releases/download/xmage_1.4.62V1/mage-full_1.4.62-dev_2026-10-03_20-47.zip
sha256sum mage.zip   # d256251a...
unzip -q mage.zip

cd /path/to/mtg-ai/engine/xmage
R=~/xmage/xmage/mage-server
CP=$(find $R -name '*.jar' | tr '\n' ':')
mkdir -p /tmp/xmage-cls && javac -cp "$CP" -d /tmp/xmage-cls *.java

# vocabulary (only when the XMage version changes)
(cd $R && java -Djava.awt.headless=true -cp /tmp/xmage-cls:$CP VocabDump $OLDPWD/../vocab/dsk_vocab.json)

# 4 games, random bot on dsk_ug vs XMage AI on dsk_uw, seed 1
python3 run_games.py $R /tmp/xmage-cls $PWD/decks/dsk_ug.dck $PWD/decks/dsk_uw.dck 4 1 /tmp/games.jsonl
```

Decisions go to `/tmp/games.jsonl`, the JVM log (leaks, unmapped abilities and choices, abilities on the board
with no key, rejected moves) to
`/tmp/games.jvm.log`. `LEAKTEST=1` plants deliberate leaks to show the checker catches them.

VocabDump keeps the `tokens` list already in the file (token names come from recorded games, not the card list).

Same seed does not reproduce the same game (XMage's own randomness), so every action is logged.

## Known XMage bugs (1.4.62)

- **Layer timestamps after a face-down permanent appears** (found 2026-10-20 in a Claude-vs-Claude review, reproduced
  on the unmodified jars; report `/mnt/project-files/claude-games/reviews/xmage-first-strike-check-2026-10-20.md`).
  `ContinuousEffects.apply()` only re-reads the layer-1 effect group while copy or face-down effects exist, so its
  snapshot can be many turns old. When a manifest later enters, every effect missing from that stale snapshot gets a
  fresh timestamp in the order the decks were loaded (seat A first), not the order the cards entered. Example: Ethereal
  Armor, then Unable to Scream on the same creature correctly removes first strike, but once a manifest enters the
  creature has first strike again. Rare (needs two conflicting layer effects plus a later face-down permanent); the
  observation's `keywords` show what the engine applies, so the seat sees the engine's (wrong) answer. Not fixed: under
  build option 1 we fork only if a DSK bug blocks us.
