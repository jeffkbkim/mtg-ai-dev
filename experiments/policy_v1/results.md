# Policy v1 results (draft: numbers only, as measured)

## Model: 200-l1

- Checkpoint `data/runs/2026-11-03_224849_200-l1/best.pt` (sha256 `ca31f054b258…`), best val epoch; code at bf976e8
  (model) / a400a73 (trainer). 30.9k parameters, 1 transformer layer.
- Data: `17lands-200-clean` cache, 200 chunks of the DSK 17lands turn replay, recorded + unique labels, pre-game
  filler rows dropped; split by draft. Seed 0.
- Played through `policy.onnx` (onnxruntime matches PyTorch to 1.9e-6), greedy.

## Held-out (test split, 146,211 decisions): `heldout-200-l1.json`

| kind | n | uniform (random legal) | type prior | kind+type prior | policy |
|---|---:|---:|---:|---:|---:|
| all | 146,211 | 42.8% | 77.1% | 77.4% | **88.3%** (loss 0.276) |
| PRIORITY | 97,589 | 42.6% | 86.4% | 86.4% | 93.3% |
| ATTACK | 21,420 | 43.4% | 54.1% | 54.1% | 78.2% |
| USE | 12,155 | 50.0% | 85.5% | 85.5% | 90.4% |
| BLOCK | 5,561 | 40.2% | 60.6% | 60.6% | 68.1% |
| TARGET | 5,376 | 31.2% | 27.7% | 33.2% | 71.4% |
| CHOOSE_CARDS | 1,905 | 49.9% | 50.0% | 50.0% | 58.7% |
| CHOOSE | 1,250 | 32.6% | 25.8% | 37.7% | 62.2% |

Top-1 accuracy, ties counted 1/k. Agreement with 17lands players' moves, not playing strength.

## Games (2026-11-05): `games-200-l1-2026-11-05.json`

400 games each: 100 deck pairs from `engine/xmage/decks/17lands-good-v2`, 4 games per pair (each deck, on the play
and on the draw). XMage 1.4.62, harness commit 2b5697f. 95% intervals.

| seat A | vs | W-L | win rate | Wilson | deck-pair bootstrap | seed |
|---|---|---:|---:|---|---|---:|
| 200-l1 | random bot | 145-255 | 36.2% | 31.7-41.1% | 31.0-41.5% | 1 |
| 200-l1 | XMage AI (CP7, skill 2) | 33-367 | 8.2% | 5.9-11.4% | 5.5-11.0% | 2 |
| random bot | XMage AI (same deck pairs) | 58-342 | 14.5% | 11.4-18.3% | 11.0-18.0% | 2 |

- The policy loses to the random bot and does worse than the random bot against XMage's AI.
- It passes its own first main phase with a land drop available 17-21% of the time (random bot 6%).
- Random fallbacks (decisions the encoder can't map, DAMAGE): 0.1-0.2% of the policy's decisions.
- Raw runs (configs, schedules, per-decision logs): `/mnt/project-files/evals/2026-11-05/`.
