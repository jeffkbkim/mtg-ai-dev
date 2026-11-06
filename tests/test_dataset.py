import gzip
import json
import math
from collections import Counter
from pathlib import Path

import pytest
import torch

from engine.baselines import ActionTypePrior, evaluate, uniform_logits
from engine.batch_config import BatchConfig
from engine.dataset import DecisionDataset, build, build_17lands, draft_split, make_loaders, split_of
from engine.encode import Vocab
from synthetic.fake_batch import validate_batch

FIXTURE = Path(__file__).parent / "fixtures" / "xmage_decisions_sample.jsonl"


def test_split_is_fixed_per_game_and_about_80_10_10():
    keys = [f"run/part1/game{i}" for i in range(5000)]
    assert [split_of(k) for k in keys] == [split_of(k) for k in keys]
    share = Counter(split_of(k) for k in keys)
    assert abs(share["train"] / 5000 - 0.8) < 0.03 and abs(share["val"] / 5000 - 0.1) < 0.03


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    """30 copies of the sample file as 30 games, cached like the real data."""
    tmp = tmp_path_factory.mktemp("games")
    lines = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    rows = []
    for g in range(30):
        f = tmp / f"game{g}.jsonl"
        f.write_text("".join(json.dumps(d) + "\n" for d in lines))
        rows.append({"run": "test", "part": "part1", "game": g, "file": str(f), "verdict": "clean"})
    rows.append({"run": "test", "part": "part1", "game": 99, "file": "missing", "verdict": "suspect"})  # not read
    manifest = tmp / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = tmp / "cache"
    summary = build([manifest], out, require_keywords=False)  # the sample predates keywords in recordings
    return out, summary, len(lines)


def test_whole_games_go_to_one_split(cache):
    out, summary, per_game = cache
    assert sum(summary["games"].values()) == 30
    for split, n in summary["decisions"].items():
        assert n == per_game * summary["games"][split]
    seen = [k for keys in summary["game_splits"].values() for k in keys]
    assert len(seen) == len(set(seen))


def test_train_also_adds_games_to_train_only(cache, tmp_path):
    out, clean, _ = cache
    manifest = out.parent / "manifest.jsonl"
    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    games = [r for r in rows if r["verdict"] == "clean"]
    for r in games[:10]:  # pretend 10 more games are suspect copies
        rows.append({**r, "game": 100 + r["game"], "verdict": "suspect"})
    rows = [r for r in rows if r["file"] != "missing"]
    m2 = tmp_path / "manifest.jsonl"
    m2.write_text("".join(json.dumps(r) + "\n" for r in rows))
    both = build([m2], tmp_path / "cache", train_also=("suspect",), require_keywords=False)
    assert both["game_splits"]["val"] == clean["game_splits"]["val"]
    assert both["game_splits"]["test"] == clean["game_splits"]["test"]
    assert both["games"]["train"] == clean["games"]["train"] + 10


def test_loader_batches_follow_the_contract(cache):
    out, summary, _ = cache
    loaders = make_loaders(out, batch_size=16)
    batch = next(iter(loaders["train"]))
    validate_batch(batch, BatchConfig.from_vocab())
    assert batch["label"].shape == (16,)
    assert len(loaders["val"].dataset) == summary["decisions"]["val"]


def test_cache_with_another_layout_is_refused(cache, tmp_path):
    out, _, _ = cache
    saved = torch.load(out / "val.pt", weights_only=False)
    saved["layout"]["card_features"] = saved["layout"]["card_features"][:-1]
    torch.save(saved, tmp_path / "val.pt")
    with pytest.raises(ValueError, match="rebuild"):
        DecisionDataset(tmp_path / "val.pt", Vocab.load())


def test_uniform_baseline_scores_log_a_and_one_over_a(cache):
    out, _, _ = cache
    loader = make_loaders(out, batch_size=8)["val"]
    sizes = [len(x.action_types) for x in loader.dataset]
    r = evaluate(uniform_logits, loader)["all"]
    assert r["loss"] == pytest.approx(sum(math.log(a) for a in sizes) / len(sizes), abs=1e-5)
    assert r["acc"] == pytest.approx(sum(1 / a for a in sizes) / len(sizes), abs=1e-5)


def test_type_prior_beats_uniform_on_its_own_training_data(cache):
    out, _, _ = cache
    loaders = make_loaders(out, batch_size=8)
    prior = ActionTypePrior(loaders["train"])
    assert evaluate(prior, loaders["train"])["all"]["loss"] < evaluate(uniform_logits, loaders["train"])["all"]["loss"]


@pytest.fixture(scope="module")
def chunks(tmp_path_factory):
    """3 chunks of 17lands-style rows: the sample decisions as games of 12 drafts, a quarter of rows ambiguous."""
    tmp = tmp_path_factory.mktemp("chunks")
    lines = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    paths, n = [], 0
    for c in range(3):
        rows = []
        for g in range(4):
            draft = f"draft{c * 4 + g}"
            for i, d in enumerate(lines):
                rows.append({**d, "draft_id": draft, "game": f"{draft}/1", "seat": "A",
                             "label": "ambiguous" if i % 4 == 3 else "recorded"})
                n += i % 4 != 3
        p = tmp / f"b000{c}" / "decisions.jsonl.gz"
        p.parent.mkdir()
        with gzip.open(p, "wt") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)
        paths.append(p)
    out = tmp / "cache"
    return out, build_17lands(paths, out, workers=2), n


def test_17lands_build_keeps_labels_and_splits_by_draft(chunks):
    out, summary, kept = chunks
    assert summary["skipped_by_reason"]["label ambiguous"] > 0
    assert sum(summary["decisions"].values()) == kept
    assert sum(summary["files"].values()) == kept and len(summary["files"]) == 9  # 3 chunks x 3 splits
    for split in ("val", "test"):
        for x in DecisionDataset(sorted(out.glob(f"{split}-*.pt"))):
            assert draft_split(x.meta["draft_id"]) == split and x.meta["label"] == "recorded"


@pytest.mark.parametrize("workers", [0, 2])
def test_17lands_train_streams_every_decision_once_per_epoch(chunks, workers):
    out, summary, _ = chunks
    loader = make_loaders(out, batch_size=8, workers=workers)["train"]
    assert len(loader.dataset) == summary["decisions"]["train"]
    orders = []
    for _ in range(2):
        seen = []
        for batch in loader:
            validate_batch(batch, BatchConfig.from_vocab())
            seen += [(n, a, y) for n, a, y in zip(batch["card_mask"].sum(1).tolist(),
                                                   batch["action_mask"].sum(1).tolist(), batch["label"].tolist())]
        assert len(seen) == summary["decisions"]["train"]
        orders.append(seen)
    assert sorted(orders[0]) == sorted(orders[1])
    assert orders[0] != orders[1]  # a new order each epoch, also when workers hold copies of the dataset


def test_loader_workers_give_the_same_val_batches(chunks):
    out, _, _ = chunks
    plain, background = make_loaders(out, batch_size=8)["val"], make_loaders(out, batch_size=8, workers=2)["val"]
    for a, b in zip(plain, background, strict=True):
        assert all(torch.equal(a[k], b[k]) for k in a if torch.is_tensor(a[k]))


def test_draft_split_matches_the_frozen_17lands_split():
    pytest.importorskip("polars")
    from seventeenlands.prepare import split_of as frozen
    for i in range(200):
        assert draft_split(f"d{i}") == {"validation": "val"}.get(frozen(f"d{i}"), frozen(f"d{i}"))


def test_17lands_build_drops_turn_0_rows_past_the_record(tmp_path):
    """turn_replay writes unscripted decisions as turn 0: only mulligans and bottoms among them are real."""
    lines = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    base = {"draft_id": "draft0", "game": "draft0/1", "seat": "A", "label": "recorded"}
    rows = ([{**d, **base, "turn": 0, "prompt": "Mulligan? Your hand has 7 cards"} for d in lines[:3]]
            + [{**d, **base, "turn": 0, "prompt": "Put Fear of Immobility on the bottom of your library"}
               for d in lines[3:5]]
            + [{**d, **base, "turn": 0} for d in lines[5:12]]  # filler: the game went on past the record
            + [{**d, **base, "turn": 4} for d in lines[12:]])
    p = tmp_path / "b0000" / "decisions.jsonl.gz"
    p.parent.mkdir()
    with gzip.open(p, "wt") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    summary = build_17lands([p], tmp_path / "cache")
    assert summary["skipped_by_reason"]["turn 0 past the record (replay filler)"] == 7
    assert sum(summary["decisions"].values()) == 3 + 2 + len(lines[12:])


def test_17lands_chunks_of_two_runs_get_their_own_cache_files(tmp_path):
    """Every replay run numbers its chunks from b0000: the run's folder keeps their cache files apart."""
    lines = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    paths = []
    for run in ("dsk50k", "dsk50k-2"):
        p = tmp_path / run / "b0000" / "decisions.jsonl.gz"
        p.parent.mkdir(parents=True)
        with gzip.open(p, "wt") as f:
            f.writelines(json.dumps({**d, "draft_id": f"{run}-d{i}", "game": f"{run}-d{i}/1", "seat": "A",
                                     "label": "recorded", "turn": 3}) + "\n" for i, d in enumerate(lines))
        paths.append(p)
    summary = build_17lands(paths, tmp_path / "cache")
    assert sum(summary["files"].values()) == 2 * len(lines)
    assert {n.split("-", 1)[1].rsplit(".", 1)[0] for n in summary["files"]} == {"dsk50k-b0000", "dsk50k-2-b0000"}
    with pytest.raises(ValueError, match="same cache name"):
        build_17lands([paths[0], paths[0]], tmp_path / "cache2")


def test_17lands_set_labels_reach_the_batch_only_when_built_in(tmp_path):
    """ambiguous_set rows keep every option that fits the record; their batches say so, plain caches' batches don't."""
    lines = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    d = next(x for x in lines if len(x["options"]) >= 2)
    base = {"draft_id": "draft0", "game": "draft0/1", "seat": "A", "turn": 3}
    rows = [{**d, **base, "label": "ambiguous_set", "choice": 0, "consistent": [0, 1], "world_share": 1.0},
            {**d, **base, "label": "alternative", "choice": 1, "world_share": 0.5},
            {**d, **base, "label": "recorded", "choice": 0}]
    p = tmp_path / "run" / "b0000" / "decisions.jsonl.gz"
    p.parent.mkdir(parents=True)
    with gzip.open(p, "wt") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    split = draft_split("draft0")

    build_17lands([p], tmp_path / "plain")
    plain = next(iter(make_loaders(tmp_path / "plain", batch_size=8)[split]))
    assert "label_set" not in plain and len(plain["label"]) == 1   # only the recorded row

    build_17lands([p], tmp_path / "sets", labels=("recorded", "unique", "ambiguous_set", "alternative"))
    batch = next(iter(make_loaders(tmp_path / "sets", batch_size=8)[split]))
    assert batch["label_set"][:, :2].tolist() == [[True, True], [False, True], [True, False]]
    assert batch["weight"].tolist() == [1.0, 0.5, 1.0]


def test_17lands_outcomes_reach_the_batch_and_games_without_one_are_skipped(tmp_path):
    """--outcomes adds the game's result (seat A won?) to every example; a game with no result is skipped, not guessed."""
    lines = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    base = {"draft_id": "draft0", "seat": "A", "turn": 3, "label": "recorded"}
    rows = [{**d, **base, "game": "g1"} for d in lines[:4]] + [{**d, **base, "game": "g2"} for d in lines[4:6]]
    p = tmp_path / "run" / "b0000" / "decisions.jsonl.gz"
    p.parent.mkdir(parents=True)
    with gzip.open(p, "wt") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    outcomes = tmp_path / "outcomes.jsonl.gz"
    with gzip.open(outcomes, "wt") as f:
        f.write(json.dumps({"game": "g1", "draft_id": "draft0", "won": True, "on_play": True, "num_turns": 9}) + "\n")

    summary = build_17lands([p], tmp_path / "cache", outcomes=outcomes)
    assert summary["skipped_by_reason"]["no 17lands result for the game"] == 2
    batch = next(iter(make_loaders(tmp_path / "cache", batch_size=8)[draft_split("draft0")]))
    assert batch["won"].tolist() == [1.0] * 4

    build_17lands([p], tmp_path / "plain")
    assert "won" not in next(iter(make_loaders(tmp_path / "plain", batch_size=8)[draft_split("draft0")]))
