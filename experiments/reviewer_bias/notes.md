# Reviewer bias by colour pair (2026-10-26)

`check.py` finds 363 decks the deck reviewer (v1 prompt) rated and fits rating ~ card quality (mean GIH WR of nonland
cards over all 17lands games) + drafter win-rate bucket. Records are not used. Results in `results.md`.

- The fit is weak (card quality even gets a small negative weight), so residuals are a rough guide, not proof.
- UG: mean rating 2.68, 0 of 59 rated 4/5, residual -0.34 +- 0.06 (the lowest pair) although UG is 3rd on 17lands
  (55.6%). Manifest-tagged decks: -0.24 +- 0.05. UR -0.18. BG +0.33, BR +0.26.
- UG/manifest concerns: "few creatures" 55 of 85, removal 30, top end 19, threat density 18.
- Fix (review_decks.py v2 prompt, `BODIES_RULE`): count manifest dread, creature tokens and creature recursion as bodies.
- Test set (`check.py --retest 20`, REVIEW_SYSTEM=v2, $0.85): 20 UG/manifest decks 2.75 -> 2.90 (4/5: 0 -> 2), 20
  control decks of other pairs 3.00 -> 3.05 (4/5: 2 -> 4; 3 up, 2 down). A small, real lift for UG/manifest; control
  barely moves.
- UG shortlist (30) re-reviewed with v2 ($0.60): 2/5 15 -> 10, 3/5 15 -> 20, still none at 4/5. The v2 pool's 10 UG
  decks ($0.19): unchanged except good_96 2 -> 3. One UG deck from the test set (draft deaa6a52, UG splashing W, passes
  every pool filter) rated 4/5 and is added as v2 good_111 ★★.
- The rest of UG's gap reads as the reviewer's view of UG's removal and threats, not the creature count.
