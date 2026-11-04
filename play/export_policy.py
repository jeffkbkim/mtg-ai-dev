"""Export a trained policy checkpoint (training/trainer.py's best.pt) to ONNX, for play/policy_player.py.

    uv run --group brain --with onnx python play/export_policy.py \\
        --checkpoint data/runs/2026-11-03_224849_200-l1/best.pt --out data/policies/200-l1

Writes <out>/policy.onnx and <out>/policy.json (what was exported, so every game result can name its model):
checkpoint sha256, epoch and val numbers, model config, the sha256 of each model/*.py file used, the git commit and
whether model/ had uncommitted changes, the vocab and encoder hashes, torch and onnxruntime versions.

Why ONNX: the game runner needs the model's forward pass and nothing else. onnxruntime runs the exported graph on
CPU in a fraction of a millisecond per decision for a model this size, without the training code, and the file is
frozen: later edits to model/ can't change a model that is already being evaluated.

The export is checked before it is written: every decision in --sample is run through both PyTorch and onnxruntime,
and the two must agree (same best option, scores within 1e-4).
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.encode import VOCAB_PATH, Unmapped, Vocab, collate, encode_decisions  # noqa: E402
from model.batch import Batch  # noqa: E402
from model.model import Model  # noqa: E402

# collate's keys in a fixed order; the exported graph keeps only the ones the forward reads
INPUTS = ["card_ids", "card_features", "ability_ids", "ability_features", "card_modes", "ability_modes",
          "global_state", "active_edges", "action_types", "action_sources", "action_targets", "action_abilities",
          "action_target_players", "action_named_options", "card_mask", "ability_mask", "action_mask"]
# which dimension of each input can change from one decision to the next
DYNAMIC = {"card_ids": {1: "N"}, "card_features": {1: "N"}, "ability_ids": {1: "N_a"}, "ability_features": {1: "N_a"},
           "card_modes": {1: "N", 2: "K_m"}, "ability_modes": {1: "N_a", 2: "K_m"},
           "active_edges": {2: "M", 3: "M"}, "action_types": {1: "A"}, "action_sources": {1: "A"},
           "action_targets": {1: "A"}, "action_abilities": {1: "A"}, "action_target_players": {1: "A"},
           "action_named_options": {1: "A"}, "card_mask": {1: "N"}, "ability_mask": {1: "N_a"},
           "action_mask": {1: "A"}, "global_state": {}}
for _axes in DYNAMIC.values():
    _axes[0] = "B"  # batch size: 1 in games, 256 in experiments/policy_v1/heldout.py


class Forward(torch.nn.Module):
    """The model's forward with plain tensors in, so ONNX can name each input."""

    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, *tensors):
        batch = dict(zip(INPUTS, tensors))
        return self.model(Batch(**batch, label=torch.zeros(tensors[0].shape[0], dtype=torch.long)))


class PlainRMSNorm(torch.nn.Module):
    """nn.RMSNorm written out in basic ops, for export only (the ONNX exporter has no rms_norm op).

    Same math as torch: x / sqrt(mean(x^2) + eps) * weight, with eps = the float32 machine epsilon when the layer
    was built with eps=None. The PyTorch-vs-onnxruntime check below compares against the original model.
    """

    def __init__(self, norm: torch.nn.RMSNorm):
        super().__init__()
        self.weight = norm.weight
        self.eps = norm.eps if norm.eps is not None else torch.finfo(torch.float32).eps
        self.dims = tuple(range(-len(norm.normalized_shape), 0))

    def forward(self, x):
        y = x * torch.rsqrt(x.pow(2).mean(dim=self.dims, keepdim=True) + self.eps)
        return y * self.weight if self.weight is not None else y


def plain_norms(module: torch.nn.Module) -> torch.nn.Module:
    """A copy of the model with every nn.RMSNorm replaced by PlainRMSNorm (shares the weights)."""
    import copy
    module = copy.deepcopy(module)
    for name, child in list(module.named_modules()):
        for attr, sub in list(child.named_children()):
            if isinstance(sub, torch.nn.RMSNorm):
                setattr(child, attr, PlainRMSNorm(sub))
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT).stdout.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--checkpoint", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--name", help="short name for reports (default: the checkpoint's run folder)")
    ap.add_argument("--sample", type=Path, default=ROOT / "tests/fixtures/xmage_decisions_sample.jsonl",
                    help="recorded decisions (JSON lines) to check PyTorch and onnxruntime agree on")
    ap.add_argument("--opset", type=int, default=18)
    args = ap.parse_args()

    ckpt = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    model = Model(**ckpt["model_config"])
    model.load_state_dict(ckpt["model"])
    model.eval()  # dropout off: games use the model as validation did
    wrapper = Forward(model).eval()

    vocab = Vocab.load()
    rows = [json.loads(line) for line in args.sample.read_text().splitlines() if line.strip()]
    examples, problems = encode_decisions([r for r in rows if r.get("type", "decision") == "decision"], vocab)
    if not examples:
        sys.exit(f"no encodable decisions in {args.sample}: {problems}")
    batches = [collate([x]) for x in examples]

    # trace on several decisions padded together, so no dimension (batch, options, cards) is traced at size 1, which
    # the tracer could bake in as a constant
    trace = collate(examples[:8])
    args.out.mkdir(parents=True, exist_ok=True)
    onnx_path = args.out / "policy.onnx"
    torch.onnx.export(Forward(plain_norms(model)).eval(), tuple(trace[k] for k in INPUTS), str(onnx_path), input_names=INPUTS,
                      output_names=["logits"], dynamic_axes={**DYNAMIC, "logits": {0: "B", 1: "A"}},
                      opset_version=args.opset, dynamo=False)

    import onnxruntime
    session = onnxruntime.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    used = [i.name for i in session.get_inputs()]
    worst, disagree = 0.0, 0
    with torch.no_grad():
        for b in batches:
            want = wrapper(*(b[k] for k in INPUTS))[0].numpy()
            got = session.run(None, {k: b[k].numpy() for k in used})[0][0]
            finite = want > float("-inf")
            worst = max(worst, float(abs(want[finite] - got[finite]).max()))
            disagree += int(want.argmax() != got.argmax())
    if worst > 1e-4 or disagree:
        onnx_path.unlink()
        sys.exit(f"onnxruntime does not match PyTorch: max |diff| {worst:.2e}, {disagree} different best options")

    model_files = sorted((ROOT / "model").glob("*.py"))
    meta = {
        "name": args.name or args.checkpoint.parent.name,
        "checkpoint": str(args.checkpoint),
        "checkpoint_sha256": sha256(args.checkpoint),
        "epoch": ckpt.get("epoch"),
        "val": ckpt.get("val"),
        "model_config": ckpt["model_config"],
        "parameters": sum(p.numel() for p in model.parameters()),
        "onnx_inputs": used,
        "model_files_sha256": {f.name: sha256(f) for f in model_files},
        "git_commit": git("rev-parse", "HEAD"),
        "model_dir_uncommitted": bool(git("status", "--porcelain", "--", "model")),
        "vocab_sha256": sha256(VOCAB_PATH),
        "encode_py_sha256": sha256(ROOT / "engine/encode.py"),
        "torch": torch.__version__,
        "onnxruntime": onnxruntime.__version__,
        "check": {"sample": str(args.sample), "decisions": len(batches), "max_abs_diff": worst},
    }
    (args.out / "policy.json").write_text(json.dumps(meta, indent=1))
    print(f"wrote {onnx_path} ({onnx_path.stat().st_size // 1024} KB), inputs {used}")
    print(f"PyTorch vs onnxruntime on {len(batches)} decisions: max |diff| {worst:.1e}, same best option on all")
    if meta["model_dir_uncommitted"]:
        print("note: model/ has uncommitted changes; policy.json keeps each file's sha256")


if __name__ == "__main__":
    main()
