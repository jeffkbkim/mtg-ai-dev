# XMage seat

A Java player class that sits in a seat of a real XMage game and hands every decision to Python.
Built against the **unmodified XMage 1.4.62 release jars** (build option 1), plus two patched XMage classes compiled
with ours (see "Our patches to XMage"; Jeff chose to patch on 2026-10-22).

- `PySeat.java`: the seat. Subclasses XMage's `ComputerPlayer`, sends each real decision as one JSON line
  over a localhost socket and plays the option Python picks. Forced decisions (only one legal option) are
  answered in Java. Rejected moves and unmapped abilities are logged, never hidden. Three behaviours are switched on
  only by `TwoSeatMatch` (the Claude games, since 2026-11-06), so 17lands replays and policy evaluations stay
  comparable: `payerV2` (restricted mana first, lands before other permanents, never the paid ability's own source,
  colours kept open, my permanents' ability costs counted), `askX` (decision kind `X`) and `keepBeforeBottom`
  (London mulligan: keep or mulligan on the new seven, then the bottom cards; XMage asks bottom first), and since
  2026-11-08 `costlyManaAsk` (the automatic payer never uses mana abilities that cost more than {T}, like Black
  Lotus, Lotus Petal or Treasure: they are offered as priority moves and their colour is asked; pain mana only when
  painless can't pay; an all-generic cost is paid by one exact source like Sol Ring before lands; lands and Moxen
  weighed together for generic; Sol Ring-like sources also offered at priority; delve cards are the player's choice).
- `Observer.java`: builds the observation from XMage's per-seat view (`GameView`, what a human client sees),
  entries in contract order `[global | cards | stack abilities]`, plus edges. Checks every message against the
  full game state for hidden-information leaks. A card being revealed is an entry with zone `REVEALED`; a card an
  opponent revealed from its hand stays in later observations as zone `HAND`, `mine: false`, `revealed: true` while
  the same card object stays in that hand (XMage forgets reveals at every priority and update event, so Observer
  remembers them per game and seat, and forgets them when the card changes zone, the game ends or the turn is rolled
  back). A modal spell or ability on the stack lists its chosen modes as `"modes": ["<card name>#mode<i>", ...]`
  (modes are announced, so this is public). The global entry has `"lands_played"`: land drops the active player
  has made this turn (0 during mulligans), and `"my_pool"` / `"opp_pool"` (e.g. `"{B}{B}{B}"`) only while that
  player has mana floating.
- `AbilityKeys.java`: stable ability keys `"<card name>#<i>"` (printed) and `"<card name>#g<i>"` (granted to
  another object or put on a token), and named choices: `alt_cost:none` / `alt_cost:ImpendingAbility` for an
  alternative-cost prompt, `"<card name>#mode<i>"` for a mode of a modal card (printed order), `choice:<text>`
  for other named prompts.
- `VocabDump.java`: writes `engine/vocab/dsk_vocab.json` (DSK card names, ability keys and texts). Modes
  (`"<card name>#mode<i>"`) and alternative costs (`"<card name>#alt:ImpendingAbility"`) are abilities too, appended
  after the printed and granted ones so existing ids stay put. `named_options` (colours, counter types) and token
  names come from recorded games and are kept from the existing file.
- `SetCards.java`: the cards one set's draft can open (DSK, FDN: the set's play-booster cards plus its 10 Special
  Guests; CUBE: Arena Powered Cube, 2025 run, the names in `CubeList.java`, one printing each). VocabDump, CardTextDump and `SetNumbers.java` (number<TAB>name, `engine/vocab/<set>_numbers.tsv`) take the
  set from `-Dmtg.set=FDN` or `$MTG_SET`, DSK when neither is given. The leak checker knows every supported set's names.
- `SeatSpike.java`: runs N games, our seat vs XMage's AI.
- `TwoSeatMatch.java`: runs N games with both seats driven from Python (used by `play/match.py`).
- `EvalMatch.java`: plays a schedule of games (deck A, deck B, who starts) with seat A driven from Python and seat B
  either Python or XMage's AI (used by `play/eval_games.py`, see `experiments/policy_v1/README.md`).
- `CardTextDump.java`: writes `engine/vocab/<set>_card_text.json` (rules text of every card of the set as XMage
  implements it; planeswalkers' `loyalty`, and a double-faced card's other face as `back`).
- `CubeList.java`: the 2025 Arena Powered Cube as 17lands lists it (539 names XMage has, basics included) and the six
  Arena-only cube cards XMage lacks. Source and per-card coverage: `/mnt/project-files/notes/arena-cube/`.
- `run_games.py`: Python side, a random-move bot that records every decision to JSON lines.
- `SeatChoiceCheck.java`: regression check that a cost an opponent's ability makes this seat pay (Osseous Sticktwister's
  discard) offers this seat's own hand. Prints PASS or FAIL.
- `SimulationCheck.java`: regression check that questions XMage's AI asks inside its own simulations of the game
  are answered in Java and never reach Python. Prints PASS or FAIL.
- `ManaCheck.java`: regression checks for automatic mana payment: lands before creatures (Enduring Vitality lets
  creatures tap for mana), Overgrown Zealot's any-colour mana pays spells (not its face-up-only mana) while its
  face-up-only mana pays for turning a manifest face up, and generic costs don't spend the colour an instant in hand
  needs. The same boards also run with `payerV2`, plus two from the batch 01-04 reviews (a generic cost leaves a
  second colour open; Creeping Peeper's restricted mana pays for turning a manifest face up). Prints PASS or FAIL.
- `TargetCheck.java`: regression check that picking one of "one or two" targets and then DONE takes two prompts
  (XMage re-asks after any call that added a target; DONE used to be asked twice). Prints PASS or FAIL.
- `PlayableCheck.java`: regression check that two copies of a permanent each offer their activated ability (XMage's
  `getPlayable(game, true)` keeps one per rules text, so two Glimmerlights offered one Equip). Prints PASS or FAIL.
- `BecomesFaceDownCreatureEffect.java`: our patched copy of that XMage class (see "Our patches to XMage").
- `FaceDownRoomCheck.java`: regression check for that patch: a face-down Room is a vanilla 2/2, a gained ability
  stays, and a face-up Room keeps only its unlocked doors' abilities. Prints PASS or FAIL.
- `XSpellCheck.java`: regression check that a {X}{X} spell (Valgavoth's Onslaught) is cast with the largest affordable
  X (XMage's AI counted X once, asked for too much mana and the cast was refused), and that with `askX` the player
  is asked (options X = 0 to that most) and its X is used; floating mana in the pool counts toward that most.
  Prints PASS or FAIL.
- `ColorChoiceCheck.java`: regression check that "As this land enters, choose a color" (Valgavoth's Lair) is asked of
  the player (XMage flags every colour choice as a mana colour choice, which the seat answers in Java). Prints PASS or
  FAIL.
- `VeteranSurvivor.java`: our patched copy of that XMage card (see "Our patches to XMage").
- `VeteranSurvivorCheck.java`: regression check for that patch: after exiling three cards it is 5/4 with hexproof.
  Prints PASS or FAIL.
- `RevealCheck.java`: regression check that a card the opponent reveals from hand stays in this seat's observation
  (zone HAND, revealed) after priority and update events, disappears once it is shuffled away, discarded or back in
  hand as a new object or its turn is rolled back, that a card revealed from the library and put into the hand is not
  remembered, and that a never-revealed hand card never shows. Prints PASS or FAIL.
- `RoomBounceCheck.java`: regression check that Unnerving Grasp on a Room (own or the opponent's, one or both doors
  unlocked) returns it to its owner's hand as one card, the caster manifests dread, either door can be cast again for
  its own cost, and the recast Room has only that door unlocked. Prints PASS or FAIL.
- `PlaneswalkerAttackCheck.java`: regression check that an opponent's planeswalker is offered as an attack target
  (Kaito, Bane of Nightmares was never attackable): the player attacks Kaito with Bashful Beastie.
- `DamageCheck.java`: regression check that an attacker blocked by two creatures lets its player divide the damage
  (DAMAGE decisions, one per blocker), without trample (any split) and with trample (lethal to each blocker first,
  the rest to the player). Prints PASS or FAIL.
- `CostlyManaCheck.java`: regression check for `costlyManaAsk` (Cube seats): the automatic payer never spends Black
  Lotus or Lotus Petal (it did before), uses Talisman pain only when painless mana can't pay, doesn't overpay with
  Sol Ring, offers Black Lotus and Sol Ring at priority, asks the Lotus' colour and pays the next spell from the pool,
  pays Pyrokinesis' {R} from a Talisman, taps a Mox rather than a needed Mountain, lets the player delve for Murderous
  Cut, and the observation shows the pool. Each source pays a symbol the rest can't, with and without the flag: {U}{B}
  from Watery Grave + Celestial Colonnade is paid (the Grave paid {U} and the cast was refused). Prints PASS or FAIL.
- `CubeLeakCheck.java`: hidden-information regressions from the cube02 batch: Chrome Mox's imprint (a hand
  `TargetCard`) offers only my own hand, a card-name choice (Phyrexian Revoker) offers the format's names without a
  leak flag, and the leak check no longer flags a keyword ("Flash") or a name inside a visible name (Phlage's "Fury").
  Prints PASS or FAIL.
- `BlockCheck.java`: builds a combat board directly and asks XMage's AI to block (for chasing block bugs).
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
mkdir -p /tmp/xmage-cls && javac -cp "$CP" -d /tmp/xmage-cls *.java   # our classes first on the classpath (the runners do)

# vocabulary (only when the XMage version changes)
(cd $R && java -Djava.awt.headless=true -cp /tmp/xmage-cls:$CP VocabDump $OLDPWD/../vocab/dsk_vocab.json)
# another set: -Dmtg.set=FDN, writing engine/vocab/fdn_vocab.json, fdn_card_text.json (CardTextDump), fdn_numbers.tsv (SetNumbers)

# 4 games, random bot on dsk_ug vs XMage AI on dsk_uw, seed 1
python3 run_games.py $R /tmp/xmage-cls $PWD/decks/dsk_ug.dck $PWD/decks/dsk_uw.dck 4 1 /tmp/games.jsonl
```

Decisions go to `/tmp/games.jsonl`, the JVM log (leaks, unmapped abilities and choices, abilities on the board
with no key, rejected moves) to
`/tmp/games.jvm.log`. `LEAKTEST=1` plants deliberate leaks to show the checker catches them.

VocabDump keeps the `tokens` list already in the file (token names come from recorded games, not the card list).

```sh
(cd $R && java -Djava.awt.headless=true -cp /tmp/xmage-cls:$CP SeatChoiceCheck)   # expect PASS
(cd $R && java -Djava.awt.headless=true -cp /tmp/xmage-cls:$CP SimulationCheck)  # expect PASS
(cd $R && java -Djava.awt.headless=true -cp /tmp/xmage-cls:$CP ManaCheck)        # expect PASS
(cd $R && java -Djava.awt.headless=true -cp /tmp/xmage-cls:$CP TargetCheck)      # expect PASS
(cd $R && java -Djava.awt.headless=true -cp /tmp/xmage-cls:$CP PlayableCheck)    # expect PASS
(cd $R && java -Djava.awt.headless=true -cp /tmp/xmage-cls:$CP XSpellCheck)      # expect PASS
(cd $R && java -Djava.awt.headless=true -cp /tmp/xmage-cls:$CP FaceDownRoomCheck) # expect PASS
(cd $R && java -Djava.awt.headless=true -cp /tmp/xmage-cls:$CP ColorChoiceCheck) # expect PASS
(cd $R && java -Djava.awt.headless=true -cp /tmp/xmage-cls:$CP VeteranSurvivorCheck) # expect PASS
(cd $R && java -Djava.awt.headless=true -cp /tmp/xmage-cls:$CP RoomBounceCheck)  # expect PASS
(cd $R && java -Djava.awt.headless=true -cp /tmp/xmage-cls:$CP RevealCheck)      # expect PASS
(cd $R && java -Djava.awt.headless=true -cp /tmp/xmage-cls:$CP PlaneswalkerAttackCheck) # expect PASS
(cd $R && java -Djava.awt.headless=true -cp /tmp/xmage-cls:$CP DamageCheck)             # expect PASS
(cd $R && java -Djava.awt.headless=true -cp /tmp/xmage-cls:$CP CostlyManaCheck)         # expect PASS
```

Same seed does not reproduce the same game (XMage's own randomness), so every action is logged.

## Known XMage bugs (1.4.62)

- **Layer timestamps after a face-down permanent appears** (found 2026-10-20 in a Claude-vs-Claude review, reproduced
  on the unmodified jars; report `/mnt/project-files/claude-games/reviews/xmage-first-strike-check-2026-10-20.md`).
  `ContinuousEffects.apply()` only re-reads the layer-1 effect group while copy or face-down effects exist, so its
  snapshot can be many turns old. When a manifest later enters, every effect missing from that stale snapshot gets a
  fresh timestamp in the order the decks were loaded (seat A first), not the order the cards entered. Example: Ethereal
  Armor, then Unable to Scream on the same creature correctly removes first strike, but once a manifest enters the
  creature has first strike again. Rare (needs two conflicting layer effects plus a later face-down permanent); the
  observation's `keywords` show what the engine applies, so the seat sees the engine's (wrong) answer. Not patched.

## Our patches to XMage

Each patch is a copy of one XMage 1.4.62 source file (tag `xmage_1.4.62V1`, MIT License) with the change marked
`PATCH (mtg-ai)`. It is compiled with our classes, which come first on the classpath, so it replaces the class in the
release jar; the jars themselves stay unmodified. When the XMage version changes, re-copy the file from the new tag
and re-apply the marked change, or drop the patch if upstream fixed it.

- `BecomesFaceDownCreatureEffect.java`: **face-down Rooms kept their doors' abilities** (found 2026-10-22 by the game
  reviewer). A Room manifested face down should be a vanilla 2/2, but it kept both doors' abilities, locked doors
  included: a face-down Ticket Booth // Tunnel of Hate still gave an attacker double strike whenever its controller
  attacked (plan-pairs batch01 part11 game1, where it decided a combat). The face-down effect removes only the card's
  own abilities and keeps those gained from other sources; a Room's door abilities live on its halves, not in the
  card's ability list, so they counted as gained. The patch also treats abilities of a split card's halves as its own.
  Seen in 4 of 117 recorded Claude games before the patch (an own face-down Room on the battlefield). Check:
  `FaceDownRoomCheck` (FAIL on the unpatched class, PASS patched).
- `VeteranSurvivor.java`: **Veteran Survivor never got +3/+3 and hexproof** (found 2026-10-23 by the game reviewer).
  Its static ability looked for "cards exiled with this" under the ability's own zone change counter (0), while the
  Survival trigger exiles under the permanent's, so the bonus never turned on (facts-check-pairs batch01 part13: three
  cards exiled, still 3/2, then Scorching Dragonfire targeted it). The patch is the fix XMage's master branch already
  has (count by the permanent's current zone change counter). Check: `VeteranSurvivorCheck` (FAIL unpatched, PASS
  patched).
