"""Recorded games -> train / val / test decisions, cached once, served as padded batches.

    python -m engine.dataset build --manifest /mnt/project-files/claude-games/manifest.jsonl --out data/cache/claude-v1
    python -m engine.dataset build-17lands --chunks data/17lands/dsk50k/b000?/decisions.jsonl.gz --out data/cache/17lands-10
    loaders = make_loaders("data/cache/claude-v1", batch_size=64)
    for batch in loaders["train"]:            # dict of contract tensors, the same keys as collate()
        logits = model(Batch(**batch))

Decisions are split by game, never by decision: decisions of one game are near-copies of each other (the same board
one priority pass later), so a game split across train and val would let val reward remembering that game.
Each game's split comes from a hash of its name, so adding games later never moves an old game to another split.
"""

import argparse
import dataclasses
import gzip
import hashlib
import json
import random
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import torch
from torch.utils.data import DataLoader, Dataset, IterableDataset

from engine.encode import (ABILITY_FEATURES, ACTION_TYPES, CARD_FEATURES, EDGE_TYPES, GLOBAL_FEATURES, Example,
                           Vocab, collate, encode_decisions, encode_file)

SPLITS = {"train": 0.8, "val": 0.1, "test": 0.1}
GAMES_ROOT = "/mnt/project-files/claude-games"  # where manifest paths point; --games-root swaps it for a local copy
DRAFT_SPLIT_SALT = "mtg-ai-dsk-split-v1"  # seventeenlands/prepare.py's SPLIT_SALT for DSK
LABELS_17LANDS = ("recorded", "unique")  # the labels the record pins down (seventeenlands/TURN_REPLAY.md)


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


def draft_split(draft_id: str) -> str:
    """The frozen 17lands split by draft (seventeenlands/prepare.py split_of), so every 17lands dataset agrees."""
    h = int(hashlib.sha256(f"{DRAFT_SPLIT_SALT}:{draft_id}".encode()).hexdigest()[:8], 16) % 100
    return "train" if h < 80 else "val" if h < 90 else "test"


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
                by_split[split].append(_stored(x))
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


def _stored(x: Example) -> dict:
    d = dataclasses.asdict(x)
    d["card_features"] = torch.tensor(x.card_features, dtype=torch.float32)  # compact on disk
    return d


def _chunk_name(path: Path) -> str:
    """dsk50k-b0000 for .../dsk50k/b0000/decisions.jsonl.gz, b0000 for a copy at .../b0000.jsonl.gz.

    The run's folder is part of the name because every replay run numbers its chunks from b0000: the two dsk50k
    runs would otherwise write the same cache files.
    """
    if path.name == "decisions.jsonl.gz":
        return f"{path.parent.parent.name}-{path.parent.name}"
    return path.name.split(".")[0]


def _is_pregame(row: dict) -> bool:
    """A mulligan or London-mulligan bottom: the only turn-0 rows the replay actually decides from the record.

    turn_replay.py writes every decision it has no turn script for as label "recorded", turn 0. Besides the
    pre-game ones, that includes every decision after the recorded turns run out (the game keeps going in XMage
    until someone decks): option 0 each time, i.e. pass, no attack, discard the first card. Those are filler.
    """
    prompt = row.get("prompt", "")
    return prompt.startswith("Mulligan") or "bottom of your library" in prompt


def _build_chunk(chunk: Path, out: Path, labels: tuple[str, ...]) -> dict:
    """One chunk -> train-/val-/test-<chunk>.pt. Runs in its own process when building with workers.

    Each row is encoded as soon as it is read and the raw row dropped: holding a chunk's raw rows took ~5 GB.
    The rows already carry lands_played, so encoding one at a time loses nothing.
    """
    vocab = Vocab.load()
    stored: dict[str, list[dict]] = {s: [] for s in SPLITS}
    drafts: dict[str, set] = {s: set() for s in SPLITS}
    skipped: Counter = Counter()
    with gzip.open(chunk, "rt") as f:
        for line in f:
            r = json.loads(line)
            if r.get("label") not in labels:
                skipped[f"label {r.get('label')}"] += 1
                continue
            if r.get("turn") == 0 and not _is_pregame(r):
                skipped["turn 0 past the record (replay filler)"] += 1
                continue
            split = draft_split(r["draft_id"])
            drafts[split].add(r["draft_id"])
            examples, problems = encode_decisions([r], vocab, keep=("game", "draft_id", "label", "turn"))
            skipped.update(problems)
            stored[split] += [_stored(x) for x in examples]
    files = {}
    for split, rows in stored.items():
        name = f"{split}-{_chunk_name(Path(chunk))}.pt"
        torch.save({"layout": _layout(vocab), "examples": rows}, out / name)
        files[name] = len(rows)
    print(f"{_chunk_name(Path(chunk))}: {sum(files.values()):,} decisions", flush=True)
    return {"files": files, "drafts": drafts, "skipped": skipped}


def build_17lands(chunks: list[Path], out: Path, labels: tuple[str, ...] = LABELS_17LANDS, workers: int = 1) -> dict:
    """17lands turn-replay rows -> one cache file per chunk and split: train-dsk50k-b0000.pt, val-dsk50k-b0000.pt, ...

    One file per chunk because the whole train split doesn't fit in memory once there are many chunks: the train
    loader reads a few files at a time (ShardedDecisions). A game never spans two chunks and a draft's games all go to
    one split, so no game is in two files. Chunks are independent, so `workers` processes build several at once.
    """
    names = Counter(_chunk_name(Path(c)) for c in chunks)
    if clash := [n for n, k in names.items() if k > 1]:
        raise ValueError(f"chunks with the same cache name would overwrite each other: {clash}")
    out.mkdir(parents=True, exist_ok=True)
    if workers > 1:
        with ProcessPoolExecutor(workers) as pool:
            results = list(pool.map(_build_chunk, chunks, [out] * len(chunks), [labels] * len(chunks)))
    else:
        results = [_build_chunk(c, out, labels) for c in chunks]
    files = {k: v for r in results for k, v in r["files"].items()}
    drafts = {s: set().union(*(r["drafts"][s] for r in results)) for s in SPLITS}
    skipped = sum((r["skipped"] for r in results), Counter())
    decisions = {s: sum(n for k, n in files.items() if k.startswith(f"{s}-")) for s in SPLITS}
    summary = {"source": "17lands turn replay", "labels": list(labels), "chunks": [str(c) for c in chunks],
               "drafts": {s: len(d) for s, d in drafts.items()}, "decisions": decisions,
               "skipped": sum(skipped.values()), "skipped_by_reason": dict(skipped.most_common()), "files": files}
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    return summary


class DecisionDataset(Dataset):
    """One split's decisions. dataset[i] is one Example (its own N, A, ...); collate pads a list of them."""

    def __init__(self, path: Path | list[Path], vocab: Vocab | None = None):
        vocab = vocab or Vocab.load()
        paths = [path] if isinstance(path, (str, Path)) else path
        self.examples = [x for p in paths for x in _load(Path(p), vocab)]

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, i: int) -> Example:
        return self.examples[i]


def _load(path: Path, vocab: Vocab) -> list[Example]:
    saved = torch.load(path, weights_only=False)
    if saved["layout"] != _layout(vocab):
        raise ValueError(f"{path} was built with a different feature layout or vocab: rebuild it")
    return [Example(**d) for d in saved["examples"]]


class ShardedDecisions(IterableDataset):
    """Train decisions spread over many files, more than fit in memory at once.

    Each epoch reads the files in a new random order, `per_pool` at a time, and shuffles the decisions of those
    files together before handing them out. Memory holds only per_pool files, and a batch mixes the games of
    several chunks. The shuffle is a little weaker than a full one: two decisions in files of different pools
    never share a batch in that epoch.
    """

    def __init__(self, paths: list[Path], sizes: dict[str, int], vocab: Vocab, seed: int = 0, per_pool: int = 2):
        self.paths, self.vocab, self.seed, self.per_pool = paths, vocab, seed, per_pool
        self.n = sum(sizes[p.name] for p in paths)
        self.epoch = 0

    def __len__(self) -> int:
        return self.n

    def __iter__(self):
        rng = random.Random(self.seed * 1_000_003 + self.epoch)  # a different order every epoch, same per seed
        self.epoch += 1
        order = rng.sample(self.paths, len(self.paths))
        for i in range(0, len(order), self.per_pool):
            pool = [x for p in order[i:i + self.per_pool] for x in _load(p, self.vocab)]
            rng.shuffle(pool)
            yield from pool


def make_loaders(cache: str | Path, batch_size: int = 64, seed: int = 0) -> dict[str, DataLoader]:
    """train is reshuffled every epoch (seeded); val and test keep a fixed order.

    A cache made of per-chunk files (build-17lands) streams train a few files at a time and loads val and test whole.
    """
    vocab = Vocab.load()
    cache = Path(cache)
    if not (cache / "train.pt").exists():
        files = json.loads((cache / "summary.json").read_text())["files"]
        paths = {s: sorted(cache.glob(f"{s}-*.pt")) for s in SPLITS}
        train = ShardedDecisions(paths["train"], files, vocab, seed)
        loaders = {"train": DataLoader(train, batch_size=batch_size, collate_fn=collate)}
        for split in ("val", "test"):
            loaders[split] = DataLoader(DecisionDataset(paths[split], vocab), batch_size=batch_size,
                                        collate_fn=collate)
        return loaders
    loaders = {}
    for split in SPLITS:
        data = DecisionDataset(cache / f"{split}.pt", vocab)
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
    c = sub.add_parser("build-17lands", help="encode 17lands turn-replay chunks, one cache file per chunk and split")
    c.add_argument("--chunks", type=Path, nargs="+", required=True, help="decisions.jsonl.gz files")
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--labels", nargs="+", default=list(LABELS_17LANDS),
                   help="row labels to keep (recorded, unique, ambiguous, not_recorded)")
    c.add_argument("--workers", type=int, default=4, help="chunks built at once, one process each")
    args = ap.parse_args()
    if args.cmd == "build-17lands":
        s = build_17lands(args.chunks, args.out, tuple(args.labels), args.workers)
        print(json.dumps({k: v for k, v in s.items() if k not in ("files", "chunks")}, indent=1))
        return
    s = build(args.manifest, args.out, args.verdict, args.games_root, tuple(args.train_also))
    print(json.dumps({k: v for k, v in s.items() if k != "game_splits"}, indent=1))


if __name__ == "__main__":
    main()
