import json
import math
from collections import Counter
from pathlib import Path

import pytest
import torch

from engine.baselines import ActionTypePrior, evaluate, uniform_logits
from engine.batch_config import BatchConfig
from engine.dataset import DecisionDataset, build, make_loaders, split_of
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
