# Puzzle test: primer v1 vs v2 on frozen decisions (2026-10-24)

The question: does primer v2 (`play/primer/dsk_meta_v2.md`, with the new "Principles" block) fix Claude's known
mistakes without breaking decisions v1 already got right? This was checked before switching Playmat to v2.

## Method

- **Puzzles** (`play/puzzles/puzzles.jsonl`, built by `play/puzzles/build.py`): 19 recorded decisions of Claude seats
  from the Playmat games of 10-23 and 10-24.
  - 9 **bad** puzzles, where the original pick was wrong. Sources: Jeff's two confirmed errors (4741b72d #87 and
    #127/#128), the 3c4b4d2c double block, and per-turn review "mistake" flags that I re-read and agreed with.
  - 10 **control** puzzles that v1 played well: targets, a no-block, two mulligans, a chump block, and four attacks
    including a must-attack and two lethal swings. These would catch a v2 that turns passive.
  - Review flags I dropped because the better option wasn't clear from what the seat could see: 8a33eb51 A #73
    (Glimmerburst precombat also makes blockers against the Wurm) and #44 (Plains vs Forest, both defensible),
    03df1d96 B #12, bd8716e4 B #13, 4e6a2ebd B #27, #47 and #77, 4081cda6 B #30, 4741b72d B #38 and #115, and
    91d5e28f B #24. I also dropped 4081cda6 B #10, where the review's suggested play (Fear of Being Hunted) wasn't
    among the options.
  - Each puzzle stores its "acceptable" option set, the bad pick, and a "why". Where my strict reading is narrow, a
    "lenient" set is reported next to it. Multi-step ATTACK/BLOCK sequences are judged as the step was recorded.
- **Runner** (`play/puzzles/run.py`): Playmat's settings were used: `ClaudePlayer(model="claude-opus-5-5",
  effort="high", facts=True, check=True)`, no plan, primer v1 or v2.
  - Each sample is a fresh player whose `log` is set to what that seat had seen before the decision. The log is rebuilt
    from the seat's earlier records, including the original player's earlier reasons, the same way
    `ClaudePlayer.choose()` writes it.
  - So the decision arrives as the usual "The game continues ... Game log so far:" restart message. The two mulligans
    get "A new game starts."
  - The self-check is suppressed on later ATTACK/BLOCK steps of a combat, as in the game.
  - The deck is that game's `deck-<seat>.dck`. Everything except the primer is identical between v1 and v2.
- **Samples:** 3 per puzzle per primer, 114 calls in all. Results are cached in `play/puzzles/results/results.jsonl`,
  so a rerun only pays for missing samples.
- **Cost:** $4.68 (about $0.04 per sample; the first sample of each group pays the cache write).

## Results

| Puzzle | Type | Kind | Orig | Acceptable | v1 picks | v2 picks | v1 OK | v2 OK | lenient v1 / v2 |
|---|---|---|---|---|---|---|---|---|---|
| bad-4741-87 | bad | TARGET | 1 | [3] | 1 1 1 | 1 1 1 | 0/3 | 0/3 | 0/3 / 0/3 |
| bad-4741-127 | bad | ATTACK | 8 | [0] | 0 0 0 | 0 0 1 | 3/3 | 2/3 | 3/3 / 3/3 |
| bad-4741-128 | bad | ATTACK | 7 | [0] | 7 7 7 | 0 7 0 | 0/3 | 2/3 | 0/3 / 2/3 |
| bad-3c4b-30 | bad | BLOCK | 1 | [0] | 2 2 0 | 2 1 1 | 1/3 | 0/3 |  |
| bad-4741-12 | bad | PRIORITY | 4 | [1] | 4 4 4 | 1 4 4 | 0/3 | 1/3 |  |
| bad-4741-13 | bad | PRIORITY | 2 | [0] | 2 2 2 | 0 0 0 | 0/3 | 3/3 |  |
| bad-6be3-10 | bad | PRIORITY | 2 | [0, 3, 4] | 2 0 1 | 2 4 3 | 1/3 | 2/3 |  |
| bad-03df-21 | bad | PRIORITY | 1 | [2] | 1 2 1 | 1 1 2 | 1/3 | 1/3 |  |
| bad-4e6a-68 | bad | PRIORITY | 4 | [2] | 4 4 4 | 4 4 4 | 0/3 | 0/3 |  |
| ctl-c8d5-23 | control | TARGET | 5 | [5, 6] | 5 6 5 | 5 6 5 | 3/3 | 3/3 |  |
| ctl-8ecc-71 | control | ATTACK | 6 | [6] | 6 6 6 | 6 6 6 | 3/3 | 3/3 | 3/3 / 3/3 |
| ctl-4741-109 | control | BLOCK | 0 | [0] | 0 3 0 | 0 0 0 | 2/3 | 3/3 |  |
| ctl-4741-0 | control | USE | 0 | [0] | 0 0 0 | 0 0 0 | 3/3 | 3/3 |  |
| ctl-8ecc-1 | control | USE | 0 | [0] | 0 0 0 | 0 0 0 | 3/3 | 3/3 |  |
| ctl-03df-46 | control | TARGET | 3 | [0, 3] | 3 3 3 | 3 3 3 | 3/3 | 3/3 |  |
| ctl-18de-8 | control | ATTACK | 1 | [1] | 1 1 1 | 1 1 1 | 3/3 | 3/3 |  |
| ctl-c636-33 | control | ATTACK | 2 | [2, 3, 4] | 2 2 2 | 2 2 2 | 3/3 | 3/3 | 3/3 / 3/3 |
| ctl-8a33-84 | control | ATTACK | 1 | [1, 2, 3, 4, 5, 6] | 1 1 1 | 1 1 1 | 3/3 | 3/3 |  |
| ctl-3faf-21 | control | BLOCK | 2 | [2] | 2 2 2 | 2 2 2 | 3/3 | 3/3 |  |

"Orig" is the pick in the game. The picks are option indices, one per sample.

Totals:

- **Bad puzzles, samples OK:** v1 6/27, v2 11/27.
  - Fixed by v2 (v1 mostly wrong, v2 mostly right): **3**, namely 4741-13, 4741-128 and 6be3-10.
  - Better but still mostly wrong: 4741-12 (0/3 to 1/3).
  - Unchanged: 4741-87, 03df-21 and 4e6a-68.
  - Worse: 4741-127 (3/3 to 2/3; 3/3 under the lenient reading) and 3c4b-30 (1/3 to 0/3). Both were already wrong
    under v1, or wrong only on a narrow reading.
- **Control puzzles, samples OK:** v1 29/30, v2 30/30. **No control is broken by v2.** v2 attacked in every
  must-attack and lethal control (12/12 samples), so there are no signs that it turned passive.

## What the reasons show

- **Attack before casting (the clearest v2 gain).** On 4741-13, v1 tapped out for Glimmer Seeker all three times
  ("Casting Glimmer Seeker with all three lands for the biggest body"). v2 went to combat all three times
  ("Moving to combat before casting anything: the opponent is tapped out"), holding R for Turn Inside Out.
  - On 6be3-10, v2 kept the {2}{W} flip up twice (equip or Percussionist first). v1 did it once, cast Twins once, and
    once spent 3 on Trapped in the Screen.
- **Keeping the flying blocker (4741-128).** v1 sent the second Insect into the Demon every time ("Send the second
  flying Insect too"). Twice v2 kept it home: "the 2/1 flying Insect stays home as my only blocker that can chump their
  6/6 flying Demon".
- **The 4741-127 change comes from effort, not the primer.** The game ran at effort medium; at high, v1 already holds
  the Insects back 3/3. v2's one strict miss attacked with the 1/1 Clockwork Percussionist (it pays out when it dies),
  not the Insects.
- **The aura host principle didn't land (4741-87, 0/3 for both).**
  - v2 did consider the shuffle, then dismissed it: "it costs {4}{U}{U} and they have only one blue source (Island)
    on 5 lands, so that risk is far off".
  - That dismissal is a real argument, not a misread. The opponent's only blue source was one Island (Strangled
    Cemetery makes B/G).
  - Both primers still waste the +1/+0 and lifelink on a creature that can't attack or block. A Facts tag ("enchanted
    by an opponent's lock aura") may help more than primer text.
- **Unchanged misses.**
  - 4e6a-68: both primers played the untapped Island every time instead of the tapped Lakeside Shack.
  - 03df-21: both tapped out for Fear of Exposure over Dragonfire on the Slasher, 1/3 each.
  - 4741-12: Plains over Mountain. v2 found Mountain once. Another v2 sample played Plains and then planned a Turn
    Inside Out attack that the Plains made impossible.
- **3c4b-30.** Both primers mostly double-blocked the defender wall. Option 2 (Fear of Isolation first) was the first
  step of the same double block. v1's one OK sample declined because "their 2 open mana could add a trick".

## Caveats

- **Small sample:** 19 puzzles × 3 samples. A one-sample difference on a puzzle is noise. Only 4741-13 (0/3 to 3/3) is
  a clean flip.
- **My judgments:** the "acceptable" sets are my reading of the state, not ground truth. Several bad puzzles are small
  edges, like land sequencing.
- **Single-decision framing:** the player gets the rebuilt log, not the live conversation it had in the game. That log
  includes the original player's earlier reasons, which anchor both primers the same way: e.g. the plan written at
  #127 is in the log for #128.
- **Settings differ from the original games:** the puzzles ran at effort high. The 4741b72d originals were played at
  medium.
- **Agreement with these picks is not playing strength.** Puzzles are a cheap screen. The real test is games against
  fixed opponents with seat balance.

## Recommendation

Switch Playmat's Claude to primer v2.

- v2 fixes 3 of the 9 bad puzzles, with the clearest gain on the attack-before-casting principle it was written for.
- It breaks none of the 10 controls (30/30) and shows no sign of turning passive.
- Keep watching the aura-host and land-sequencing cases. v2 doesn't fix them, so they may need a Facts line rather
  than primer text.
- Confirm with real games afterwards.
