"""Held-out (test split) top-1 accuracy and loss of an exported policy against the baselines, per decision kind.

    uv run --group brain python experiments/policy_v1/heldout.py --cache data/cache/17lands-200-clean \\
        --policy data/policies/200-l1/policy.onnx --out experiments/policy_v1/heldout-200-l1.json

The test split has never been used for training or for picking the checkpoint (the trainer picks best.pt on val),
so it is the honest number. Splits are by draft (engine/dataset.py draft_split), so no game in test shares a draft
with a game in train.

Models compared, every one scored by engine/baselines.py evaluate() (ties count 1/k):
- uniform: a random legal option ("random-legal"). Its accuracy is the average of 1/(options).
- type prior: score = how often an option of this action type is picked in train.
- kind+type prior: the same, learned separately per decision kind (most-frequent pick of that kind).
- the policy, run through onnxruntime: the exact file the game runner plays, not the PyTorch checkpoint.

Writes the table to stdout and, with --out, a JSON file with the numbers plus what produced them (cache summary,
policy.json, git commit).
"""
import argparse, json, subprocess, sys, time
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engine.baselines import ActionTypePrior, KindTypePrior, evaluate, report, uniform_logits  # noqa: E402
from engine.dataset import make_loaders  # noqa: E402


class OnnxLogits:
    def __init__(self, path):
        import onnxruntime
        self.session = onnxruntime.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        self.inputs = [i.name for i in self.session.get_inputs()]

    def __call__(self, batch):
        out = self.session.run(None, {k: batch[k].numpy() for k in self.inputs})[0]
        return torch.from_numpy(np.ascontiguousarray(out))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", required=True, type=Path)
    ap.add_argument("--policy", required=True, type=Path)
    ap.add_argument("--split", default="test")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    t0 = time.time()
    loaders = make_loaders(args.cache, batch_size=256)
    held = loaders[args.split]
    results = {
        "uniform": evaluate(uniform_logits, held),
        "type prior": evaluate(ActionTypePrior(loaders["train"]), held),
        "kind+type prior": evaluate(KindTypePrior(loaders["train"]), held),
        "policy": evaluate(OnnxLogits(args.policy), held),
    }
    print(f"{args.split} split of {args.cache} ({results['policy']['all']['n']} decisions):")
    print(report(results))
    if args.out:
        meta_path = args.policy.with_suffix(".json")
        summary = json.loads((args.cache / "summary.json").read_text()) if (args.cache / "summary.json").exists() else {}
        args.out.write_text(json.dumps({
            "split": args.split, "cache": str(args.cache),
            "cache_summary": {k: v for k, v in summary.items() if k not in ("files", "chunks", "game_splits")},
            "policy": str(args.policy),
            "policy_meta": json.loads(meta_path.read_text()) if meta_path.exists() else None,
            "code_commit": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                                          cwd=ROOT).stdout.strip(),
            "seconds": round(time.time() - t0), "results": results,
        }, indent=1))
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
