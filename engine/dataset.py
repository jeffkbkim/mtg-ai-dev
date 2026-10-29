"""Recorded games -> train / val / test decisions, cached once, served as padded batches.

    python -m engine.dataset build --manifest /mnt/project-files/claude-games/manifest.jsonl --out data/cache/claude-v1
    loaders = make_loaders("data/cache/claude-v1", batch_size=64)
    for batch in loaders["train"]:            # dict of contract tensors, the same keys as collate()
        logits = model(Batch(**batch))

Decisions are split by game, never by decision: decisions of one game are near-copies of each other (the same board
one priority pass later), so a game split across train and val would let val reward remembering that game.
Each game's split comes from a hash of its name, so adding games later never moves an old game to another split.
"""

import argparse
import dataclasses
import hashlib
import json
from collections import Counter
from pathlib import Path

import torch
from torch.utils.data import DataLoader, Dataset

from engine.encode import (ABILITY_FEATURES, ACTION_TYPES, CARD_FEATURES, EDGE_TYPES, GLOBAL_FEATURES, Example,
                           Vocab, collate, encode_file)

SPLITS = {"train": 0.8, "val": 0.1, "test": 0.1}
GAMES_ROOT = "/mnt/project-files/claude-games"  # where manifest paths point; --games-root swaps it for a local copy


def game_key(row: dict) -> str:
    """A name for the game that is the same on every machine (manifest file paths are not)."""
    return f"{row['run']}/{row['part']}/game{row['game']}"


def split_of(key: str) -> str:
    """train / val / test from a hash of the game's name: fixed per game, about 80 / 10 / 10 over many games."""
    u = int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) / 16 ** 8  # uniform in [0, 1)
    edge = 0.0
    for name, share in SPLITS.items():
        edge += share
        if u < edge:
            return name
    return name


def _layout(vocab: Vocab) -> dict:
    """What a cached example's numbers mean. A cache made with a different layout is refused, not misread."""
    return {"card_features": CARD_FEATURES, "ability_features": ABILITY_FEATURES, "global_features": GLOBAL_FEATURES,
            "edge_types": EDGE_TYPES, "action_types": ACTION_TYPES, "num_cards": vocab.num_cards,
            "num_abilities": vocab.num_abilities, "num_named_options": vocab.num_named_options}


def build(manifests: list[Path], out: Path, verdict: str = "clean", games_root: str | None = None,
          train_also: tuple[str, ...] = (), require_keywords: bool = True) -> dict:
    """Encode every game with this verdict once and save one file per split. Returns a summary.

    Games with a verdict in train_also (e.g. "suspect") go to train only, whatever their hash says, so val and test
    stay exactly the clean games of a cache built without them: the two caches' val numbers are comparable.
    """
    vocab = Vocab.load()
    by_split: dict[str, list[dict]] = {s: [] for s in SPLITS}
    games: dict[str, list[str]] = {s: [] for s in SPLITS}
    unmapped: Counter = Counter()
    for manifest in manifests:
        for line in Path(manifest).read_text().splitlines():
            row = json.loads(line)
            if row.get("verdict") != verdict and row.get("verdict") not in train_also:
                continue
            path = row["file"] if games_root is None else row["file"].replace(GAMES_ROOT, games_root, 1)
            key = game_key(row)
            split = split_of(key) if row.get("verdict") == verdict else "train"
            if require_keywords and '"keywords"' not in Path(path).read_text():
                # recorded before the seat sent keywords (2026-10-20): every has_<keyword> column would read 0
                unmapped["game skipped: recorded before the seat sent keywords"] += 1
                continue
            examples, problems = encode_file(Path(path), vocab)
            unmapped.update(problems)
            for x in examples:
                x.meta["game"] = key
                x.meta["verdict"] = row.get("verdict")
                d = dataclasses.asdict(x)
                d["card_features"] = torch.tensor(x.card_features, dtype=torch.float32)  # compact on disk
                by_split[split].append(d)
            games[split].append(key)
    out.mkdir(parents=True, exist_ok=True)
    for split, rows in by_split.items():
        torch.save({"layout": _layout(vocab), "examples": rows}, out / f"{split}.pt")
    summary = {"verdict": verdict, "train_also": list(train_also), "manifests": [str(m) for m in manifests],
               "games": {s: len(g) for s, g in games.items()},
               "decisions": {s: len(r) for s, r in by_split.items()},
               "unmapped_skipped": sum(unmapped.values()), "unmapped": dict(unmapped.most_common()),
               "game_splits": games}
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    return summary


class DecisionDataset(Dataset):
    """One split's decisions. dataset[i] is one Example (its own N, A, ...); collate pads a list of them."""

    def __init__(self, path: Path, vocab: Vocab | None = None):
        saved = torch.load(path, weights_only=False)
        if saved["layout"] != _layout(vocab or Vocab.load()):
            raise ValueError(f"{path} was built with a different feature layout or vocab: rebuild it")
        self.examples = [Example(**d) for d in saved["examples"]]

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, i: int) -> Example:
        return self.examples[i]


def make_loaders(cache: str | Path, batch_size: int = 64, seed: int = 0) -> dict[str, DataLoader]:
    """train is reshuffled every epoch (seeded); val and test keep a fixed order."""
    vocab = Vocab.load()
    loaders = {}
    for split in SPLITS:
        data = DecisionDataset(Path(cache) / f"{split}.pt", vocab)
        g = torch.Generator().manual_seed(seed)
        loaders[split] = DataLoader(data, batch_size=batch_size, shuffle=split == "train", generator=g,
                                    collate_fn=collate)
    return loaders


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="encode games once and cache train/val/test")
    b.add_argument("--manifest", type=Path, action="append", required=True)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--verdict", default="clean")
    b.add_argument("--games-root", help=f"local folder that replaces {GAMES_ROOT} in manifest paths")
    b.add_argument("--train-also", action="append", default=[], metavar="VERDICT",
                   help="also use games with this verdict, in train only (e.g. suspect)")
    args = ap.parse_args()
    s = build(args.manifest, args.out, args.verdict, args.games_root, tuple(args.train_also))
    print(json.dumps({k: v for k, v in s.items() if k != "game_splits"}, indent=1))


if __name__ == "__main__":
    main()
