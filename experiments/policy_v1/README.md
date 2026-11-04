# Policy v1 evaluation

Measures a trained imitation policy two ways: held-out move agreement (top-1 accuracy on the test split) and actual
games against fixed opponents. Agreement alone is not playing strength (AGENTS.md), so both are reported.
The write-up goes in `results.md` here, numbers as they come out.

## 1. Export the checkpoint

```sh
uv run --group brain --with onnx python play/export_policy.py \
    --checkpoint data/runs/2026-11-03_224849_200-l1/best.pt --out data/policies/200-l1
```

`policy.onnx` is the forward pass alone, frozen; `policy.json` records the checkpoint's sha256, epoch, val numbers,
model config, a sha256 of every `model/*.py`, the git commit and whether `model/` had uncommitted changes. The export
checks PyTorch and onnxruntime agree on recorded decisions before writing anything. ONNX has no RMSNorm op the
exporter can use, so the exported copy writes it out as `x * rsqrt(mean(x^2) + eps) * weight` (same math; the check
compares against the original).

## 2. Held-out accuracy

```sh
uv run --group brain python experiments/policy_v1/heldout.py --cache data/cache/17lands-200-clean \
    --policy data/policies/200-l1/policy.onnx --out experiments/policy_v1/heldout-200-l1.json
```

Test split (never used for training or for picking best.pt), overall and per decision kind, against random-legal
(`uniform`), the action-type prior, and the action-type prior per decision kind (most-frequent pick of that kind).

## 3. Games

```sh
uv run --group brain python play/eval_games.py --policy data/policies/200-l1/policy.onnx \
    --opponent random --pairs 100 --jobs 3 --seed 1 --out <runs>/200-l1-vs-random
uv run --group brain python play/eval_games.py --policy data/policies/200-l1/policy.onnx \
    --opponent xmage --pairs 100 --jobs 3 --seed 2 --out <runs>/200-l1-vs-xmage
python3 play/eval_report.py <runs>/200-l1-vs-random <runs>/200-l1-vs-xmage --json results.json
```

- Seat A is the policy (greedy: its top option), seat B the opponent: `random` (the project's random bot),
  `xmage` (ComputerPlayer7, skill 2, 1 s think, as in our engine checks) or `policy:<onnx>`. `--policy random` puts
  the random bot in seat A, the reference a policy's numbers sit next to.
- Seat balance: each deck pair from `engine/xmage/decks/17lands-good-v2` (100 real 17lands decks) is played 4 times,
  the policy on each deck, on the play and on the draw. `--pairs 100` = 400 games.
- Engine: `engine/xmage/EvalMatch.java` plays a schedule file in order; seat B can be XMage's AI.
- A decision the encoder can't map (DAMAGE splits today) is played as a random legal option and counted as a
  fallback; the report gives the rate.
- Report: win rate with a 95% Wilson interval and a deck-pair bootstrap interval (the 4 games of a pair share decks,
  so they are not independent), on-the-play / on-the-draw split, and one behaviour check: how often the policy passes
  its first main phase while a land drop is available.

Games take about 3 s each (both opponents), so 400 games with 3 engines is roughly 10 minutes. They don't need the
Mac mini: a cloud container with XMage 1.4.62 and Java 21 runs them.
