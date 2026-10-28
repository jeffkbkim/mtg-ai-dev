"""Two models with no learning beyond counting, and the evaluation every model shares.

    python -m engine.baselines --cache data/cache/claude-v1

A trained model has to beat both on val, or it has not learned anything about the board:
- uniform: every legal option equally likely. Its loss is mean(log A), the loss your model starts at.
- action-type prior: an option's score is how often options of its type get picked in train (attack, pass, cast...).
  Sees only the action types, nothing about cards or the board.

evaluate() works for any function batch -> (B, A) logits with padded options at -inf, including your model:
    evaluate(lambda batch: model(Batch(**batch)), loaders["val"])
"""

import argparse
from collections import defaultdict

import torch
import torch.nn.functional as F
from torch import Tensor

from engine.encode import ACTION_TYPES, DECISION_KINDS, GLOBAL_FEATURES

KIND_COLUMNS = [GLOBAL_FEATURES.index(f"decision_{k.lower()}") for k in DECISION_KINDS]


def uniform_logits(batch: dict) -> Tensor:
    logits = torch.zeros(batch["action_mask"].shape)
    return logits.masked_fill(~batch["action_mask"], float("-inf"))


class ActionTypePrior:
    """Score of an option = log(how often an option of this type was the one picked, in train)."""

    def __init__(self, train_loader):
        picked = torch.ones(len(ACTION_TYPES))  # +1 / +2: a type never seen gets 1/2, not 0 or 1/0
        offered = 2 * torch.ones(len(ACTION_TYPES))
        for batch in train_loader:
            types, mask = batch["action_types"], batch["action_mask"]
            offered += torch.bincount(types[mask], minlength=len(ACTION_TYPES))
            chosen = types.gather(1, batch["label"][:, None]).squeeze(1)
            picked += torch.bincount(chosen, minlength=len(ACTION_TYPES))
        self.rate = picked / offered  # (T,) chance that an offered option of this type is the pick

    def __call__(self, batch: dict) -> Tensor:
        logits = self.rate.log()[batch["action_types"]]  # (B, A)
        return logits.masked_fill(~batch["action_mask"], float("-inf"))

    def table(self) -> list[tuple[str, float]]:
        return sorted(((t, self.rate[i].item()) for i, t in enumerate(ACTION_TYPES) if t != "PAD"),
                      key=lambda r: -r[1])


@torch.no_grad()
def evaluate(logits_fn, loader) -> dict[str, dict[str, float]]:
    """Loss and accuracy overall and per decision kind (ATTACK, BLOCK, TARGET...).

    Accuracy counts a tie fairly: if the label is one of k options sharing the top score, it scores 1/k, as if the
    tie were broken at random. (argmax would pick the first one, and option order is not random: PASS comes first.)
    """
    sums = defaultdict(lambda: {"n": 0, "loss": 0.0, "acc": 0.0})
    for batch in loader:
        logits = logits_fn(batch)
        label = batch["label"]
        loss = F.cross_entropy(logits, label, reduction="none")  # (B,)
        top = logits == logits.max(dim=1, keepdim=True).values  # (B, A) options sharing the top score
        acc = top.gather(1, label[:, None]).squeeze(1) / top.sum(dim=1)  # (B,)
        kinds = batch["global_state"][:, KIND_COLUMNS].argmax(dim=1)  # (B,) index into DECISION_KINDS
        for b in range(len(label)):
            for name in ("all", DECISION_KINDS[kinds[b]]):
                s = sums[name]
                s["n"] += 1
                s["loss"] += loss[b].item()
                s["acc"] += acc[b].item()
    return {name: {"n": s["n"], "loss": s["loss"] / s["n"], "acc": s["acc"] / s["n"]}
            for name, s in sorted(sums.items(), key=lambda kv: (kv[0] != "all", -kv[1]["n"]))}


def report(results: dict[str, dict[str, dict[str, float]]]) -> str:
    """One row per decision kind, a loss / accuracy column pair per model."""
    names = list(results)
    kinds = list(next(iter(results.values())))
    head = f"{'kind':<14}{'n':>7}" + "".join(f"{m + ' loss':>22}{'acc':>7}" for m in names)
    rows = [head]
    for k in kinds:
        row = f"{k:<14}{results[names[0]][k]['n']:>7}"
        for m in names:
            r = results[m][k]
            row += f"{r['loss']:>22.3f}{r['acc']:>7.1%}"
        rows.append(row)
    return "\n".join(rows)


def main() -> None:
    from engine.dataset import make_loaders
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--split", default="val")
    args = ap.parse_args()
    loaders = make_loaders(args.cache, batch_size=256)
    prior = ActionTypePrior(loaders["train"])
    print("action-type prior (train): chance an offered option of this type is the pick")
    for t, r in prior.table():
        print(f"  {t:<14}{r:6.1%}")
    print(f"\n{args.split}:")
    print(report({"uniform": evaluate(uniform_logits, loaders[args.split]),
                  "type prior": evaluate(prior, loaders[args.split])}))


if __name__ == "__main__":
    main()
