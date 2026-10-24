# Playmat review, games of 2026-10-23 and 2026-10-24

Per-turn review of every finished game Jeff played in Playmat (seat "ffffxxxx" or "kimster"), both seats, every asked
decision. Tool: `play/review_turns.py` (Opus 5.5, effort high, one call per turn, race math first, the player's own
reasons hidden). Per-game results: `~/mtg-data/playmat-games/<date>/<game>/game0.review-turns-<seat>.json`.

Covered: 12 games (13 folders, since 91d5e28f was resumed as e9821861), 213 turns (108 Claude, 105 Jeff), 1,395
decisions. Cost: $24.44.
Skipped: 4e60eca5 (Jeff left on turn 1), the smoke tests 2ad10132 and 3ba240be, and b60dd309 (Claude against XMage's
AI, no human seat).

Severity words: **blunder** means clear and costly, **mistake** means clearly worse, **questionable** means probably
worse or the reviewer was unsure. These are a model's judgments and have not been checked by a person, apart from the
two recall cases in section 5.

## 1. Results

Jeff's decks: **UB Slasher** (Nashi, Unstoppable Slasher, Mirror Room, Vile Mutilator), **4c Swarmweaver**
(U/G/B with a white splash: Swarmweaver, Valgavoth's Onslaught, Unholy Annex), and once a **GBW** deck (Balustrade
Wurm, Overlord of the Balemurk). Claude was always dealt a random deck from the good pool. It played with facts and
self-check on and primer v1, at effort high except in 4741b72d (medium).

| Date | Game | Jeff's deck | Claude's deck | Claude | Winner | Turns | Deciding turn and why |
|---|---|---|---|---|---|---|---|
| 10-23 | 03df1d96 | UB Slasher | GR (Tyvar, Enduring Vitality) | opus high | **Jeff** | 18 | T11: Claude tapped out for Fear of Exposure and kept Scorching Dragonfire in hand, so Slasher lived. Jeff copied it with Mirror Room, and on T14 he bounced the only blocker and both Slashers took Claude from 19 to 3. |
| 10-23 | 18ded83e | UB Slasher | UB Slasher (mirror) | opus high | Claude | 11 | T6: Jeff attacked his 1/3 into the untapped Slasher, so Claude's Slasher hit back for half his life. On T7 Claude copied it with Mirror Room. |
| 10-23 | 3fafcfc0 | UB Slasher | 4c (Zimone, Shroudstomper) | opus high | Claude | 19 | T16: Jeff cast Machete instead of Vile Mutilator and then didn't block Shroudstomper (8 to 3). The drains finished him. |
| 10-23 | 4081cda6 | UB Slasher | Grixis (Hordecaller, Overlord of the Boilerbilges) | opus high | Claude | 19 | Jeff had only one Swamp all game, so his Murders and Live or Die sat in hand. On T16-18 the Gremlin swarm got through. |
| 10-23 | 4741b72d | 4c Swarmweaver | RW (Overlord of the Mistmoors) | opus **medium** | **Jeff** | 25 | T21-25: Jeff's flying 6/6 Demon from Ritual Chamber, plus the Annex drain. On T22 Claude attacked its only flying blockers into the Demon. |
| 10-23 | 4e6a2ebd | UB Slasher | UGW (Hauntwoods Shrieker) | opus high | **Jeff** | 21 | T10-11: Claude double-blocked Slasher, then Murder emptied its board. Jeff's two Vile Mutilators took over from T17. |
| 10-23 | 6be31dce | UB Slasher | RW (Patched Plaything) | opus high | **Jeff** | 24 | T18-20: Vile Mutilator forced the sacrifice of Plaything, and Mirror Room copied Mutilator. Claude's Shattered Yard burn nearly won anyway (Jeff ended at 2). |
| 10-23 | 8a33eb51 | GBW | UGW (Shrieker, Hedge Shredder) | opus high | Claude | 13 | T8-10: Jeff was the defender but took 6 unblocked twice (14 to 8 to 2) against a widening manifest board. |
| 10-23 | c6361e31 | UB Slasher | RG (Valgavoth's Onslaught) | opus high | Claude | 12 | T7-9: Jeff's slow hand had no early blockers, and the hasty Wickerfolk, pumped to 8/7 trample, did the rest. |
| 10-24 | 8ecc3f2a | 4c Swarmweaver | RW (Arabella, Hovership) | opus high | Claude | 15 | T10-14: Exorcise stayed in Jeff's hand while Hovership and then Arabella were on board. Arabella's drain was lethal. |
| 10-24 | 91d5e28f + e9821861 | 4c Swarmweaver | UW (Overlord of the Floodpits) | opus high | Claude | 16 | No blue source for most of the game. On T13 Jeff tapped out for Onslaught instead of holding Floodpits Drowner for Overlord. On T16 he quit, and the game was resumed (e9821861) and lost to a 14-creature attack. |
| 10-24 | bd8716e4 | 4c Swarmweaver | RW (Arabella, Enduring Innocence) | opus high | Claude | 18 | T11-17: Arabella was never answered. The Drowner shuffle was missed, Trapped in the Screen went on a 1/1 twice, and Arabella was bounced once instead of exiled. |

## 2. Jeff's top lessons

1. **Aim removal at the card that will kill you, and use it while you can.** In both Arabella games the removal
   was there but went elsewhere or stayed in hand.
   - 8ecc3f2a T10-14: Exorcise could hit Hovership, then Arabella, and was never cast. Arabella's drain then killed you.
   - bd8716e4 T13 and T17: Trapped in the Screen exiled a 1/1 Scavenger twice while Arabella stayed. On T15 a bounce was
     used where an exile was available.
   - Also 6be31dce T10-12: Murder stayed in hand while a 10-damage double striker was on board.
2. **When you're behind, you're the defender: keep blockers home.** An attacker stays tapped through the opponent's
   turn.
   - 18ded83e T6: the 1/3 attacked into an untapped Slasher. Summoning-sick creatures can still block, and the
     crack-back took half your life.
   - 3fafcfc0 T18 and 6be31dce T14: small attacks at 3 and 6 life left one blocker fewer.
   - The flip side: when you're ahead with a creature that wins every block (Slasher), send it (4e6a2ebd T7 and T9).
3. **Block to kill or don't block.** Before each block, ask: does my blocker kill it, and does it survive?
   - 4741b72d T9: your only flier blocked a 4/3 alone and died for nothing. T11: a 1/1 token chumped at 16 life.
   - 8ecc3f2a T12: you took 4 from a lone Clown at 9 life. The opponent had no cards and no mana, so a double block was
     a free kill.
   - 6be31dce T8: the face-down Fear of the Dark (secretly a 5/5) traded with a random 2/2.
4. **Tap and stun effects go before attackers are declared.** Tapping a creature that is already attacking does not
   stop its damage.
   - 8ecc3f2a T6, 91d5e28f T15 and e9821861 T16: Floodpits Drowner came in after attacks.
   - bd8716e4 T11: the Drowner's shuffle on stunned Arabella was available for 2 mana and went unused. That was the
     last turn it worked.
5. **Spend every turn's mana, play the land your hand needs, and discard your worst card.**
   - Mana left unused with spells in hand: 4741b72d T17 and T19, 91d5e28f T15 (Bookworm not cast), 03df1d96 T8.
   - Lands: bd8716e4 T3 (Forest instead of the only blue source, so no 2-drop).
   - Discards: Valgavoth's Onslaught or Fear of the Dark were thrown away three times (8ecc3f2a T4 and T10, bd8716e4 T7).
   - Order: cast Gremlin Tamer before the enchantment it triggers on (bd8716e4 T17).

## 3. Claude's top misplay patterns and the fix for each

Claude had 12 mistakes and 23 questionables in 108 turns, and no blunders.

| Pattern | Examples | Fix that would address it |
|---|---|---|
| **Casts its main-phase spell before combat, which taps the mana for its trick or flip**, so it can't attack well | 4741b72d #13 (T6); 6be31dce A #10 (T7); 8a33eb51 A #73 (T11, an instant cast precombat); 91d5e28f B #106 | Primer principle: "attack first; cast creatures that don't change this combat after combat; keep instants and flash for the opponent's turn". Optionally a Facts line: "N mana is needed for <trick or flip> in combat". |
| **Too passive as the beatdown**: no attack, or only one attacker, when it was ahead and the crack-back was small | 4741b72d #38, #64, #115; 4081cda6 B #30; 4e6a2ebd B #27, #77, #80 | **A race-clock line in the Facts block**: turns to kill and turns to die, counting evasion and drains, and who is the beatdown. |
| **Attacks into blockers that win, or gives up the blockers it needs** (summoning-sick creatures can still block) | 4741b72d #127/#128 (Jeff confirmed); 03df1d96 B #12 (Wickerfolk into an untapped deathtouch Slasher) | The same race-clock line. Also: in the Facts per-attacker line, list summoning-sick creatures among the untapped potential blockers, and add "your flying blockers for their flier: N". |
| **Puts an aura on a host the opponent has locked or can remove without targeting** | 4741b72d #87 (Jeff confirmed) | Primer principle: "a creature under an opposing lock aura, or exposed to a shuffle, sacrifice or exile effect that doesn't target, is a bad host; ward doesn't help". A Facts tag on creatures enchanted by an opponent's aura would also help. |
| **Land and colour choices**: fetched or played the wrong land for the spells in hand | 8a33eb51 A #44 (fetched Forest while holding a white card, with the only Plains still in the library); 4741b72d #12; 4e6a2ebd B #68; 4081cda6 B #17 | Primer principle: "fetch or play the colour that unlocks the most cards in hand". A Facts line listing each spell in hand that its colours block would also help. |
| **Taps out for removal or value instead of answering the real threat**, or casts into open mana | 03df1d96 B #21 (Fear of Exposure instead of exiling Slasher); bd8716e4 B #13 (Midnight Mayhem into 4 open blue mana, which got countered); 4e6a2ebd B #47 | Primer principle on permanent answers to recursive threats and on baiting soft counters. |

Not seen: no case where an auto-pass on Claude's own object on the stack cost anything.

## 4. Medium vs high effort (small sample: only one medium game)

- Medium, one game (4741b72d, 12 turns): 4 mistakes and 6 questionables, about 0.8 flags per turn. Both of Jeff's
  confirmed Claude errors are from this game.
- High, 11 games (96 turns): 8 mistakes and 17 questionables, about 0.26 flags per turn.
- This is not a fair comparison. 4741b72d was the longest and most complex board in the set (25 turns, a two-sided
  stall). Its seat-B review also used the first, longer prompt layout (see section 5). Medium looks worse, but one game
  can't show that.

## 5. Reviewer recall

- The old reviewer (`play/review.py`, one call per whole game) flagged 0 decisions in every game it reviewed tonight,
  including 4741b72d seat B.
- The per-turn reviewer flagged **both** of Jeff's confirmed errors in 4741b72d seat B, with no prompt change needed:
  - idx 87 (Sheltered by Ghosts on the locked Playmate): mistake, aura_or_protection_host. It named the non-targeting
    {4}{U}{U} shuffle and that ward doesn't stop it.
  - idx 127 (both Insects into the 6/6 Demon): questionable, crack_back. It reasoned "the control keeps its Demon
    blockers".
- After the first run the prompt was made shorter (unchanged state lines are dropped in long combats, and only the last
  6 turns of the log are given in full). Both turns were rerun with the shorter prompt, and both were flagged again
  (idx 87 mistake, idx 128 mistake). The stored 4741b72d B review is from the first, longer prompt.
- Recall on two known errors is a sanity check, not a measured rate. The 35 Claude flags and 71 Jeff flags have not been
  checked for false positives.

## 6. Bugs seen

| Where | What | Confidence |
|---|---|---|
| e9821861 (resumed 91d5e28f) | The resumed game's `deck-A.dck` and `deck-B.dck` have 27 and 20 cards. They miss what was already in play, so the reviewer saw cards on the board that weren't in "its deck". | checked: the files really are partial |
| 91d5e28f / e9821861 | One game is split over two folders: the first folder records a "win" for Claude when Jeff quit, and the second starts at "Game resumed at the start of turn 16". | checked |
| 8ecc3f2a A idx 42 | "Cast Exorcise" was recorded as Jeff's pick (manual_mana 2), but nothing was cast and the next decision offered it again. A cancelled cast seems to be recorded as a pick. | checked |
| 03df1d96 B idx 11, 16 (also 13, 14) | "Cast Fear of Exposure" was offered when its extra cost (tap two untapped creatures or lands) couldn't be paid. The option list doesn't check the extra cost. | reviewer, consistent with the board |
| c6361e31 B idx 25-30; 4081cda6 A idx 38 | Repeated DONE, and a Gremlin block before a must-be-blocked attacker, look like blocks XMage refused but aren't marked `refused`. Both games are on code ea358a6, before or around patch 0007. | likely |
| 4741b72d A idx 59 | The state went back after idx 54-56 (Entity Tracker face down again, Lakeside Shack back in hand). This looks like an undo or rollback that the log doesn't show. | unverified |
| 4081cda6 A idx 36 | Creeping Peeper was tapped with no recorded reason. `ui.manual_mana` 3 at idx 34 suggests Jeff tapped it by hand when paying for Meat Locker. | probably a UI slip, not an engine bug |
| bd8716e4 B idx 39 | The life totals after an Arabella combat look one point off. | unverified |
| 91d5e28f A T15 | A Drowner stun counter on a manifest isn't listed in the observation's counters. | unverified |
| many games | The public log writes Room unlocks as "unlocked the left door of a creature without name". | cosmetic, every Room game |

## 7. What needs Jeff's yes

1. **Claude player fixes from section 3**:
   - the race-clock line in the Facts block;
   - the primer principles: attack before casting creatures that don't change this combat; aura hosts and answers
     that don't target; fetching for the colours in hand.
   These change how Claude plays, so they need an A/B test with fixed decks and opponents, not this review.
2. **Default effort for the Claude AI in Playmat.** Keep high. Medium vs high needs more games before anything changes.
3. **Use `play/review_turns.py` as the main reviewer** (about $0.11 per turn, or about $2 for a whole game with both
   seats), or only for Claude seats? `play/review.py` is unchanged.
4. **Training-data filter**: should questionable flags drop Claude decisions, or only mistakes?
5. **Recording fixes**: write full deck files on a resumed game and link it to the original game; don't record a
   cancelled cast as a pick; check that refused blocks are marked in current builds.
6. **Spot-check a few new Claude flags** (e.g. 4741b72d #115, 03df1d96 B #21, 8a33eb51 A #44) and add the ones you
   agree with as `human_flags`, so the reviewer's precision can be measured.
