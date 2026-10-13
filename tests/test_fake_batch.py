import pytest
import torch

from synthetic.fake_batch import FakeBatchConfig, fake_batch, fake_batch_tensors, validate_batch


@pytest.mark.parametrize("seed", range(20))
def test_generated_batches_follow_the_contract(seed):
    cfg = FakeBatchConfig()
    validate_batch(fake_batch_tensors(cfg, batch_size=8, seed=seed), cfg)


def test_fake_batch_returns_the_batch_dataclass():
    Batch = pytest.importorskip("model.batch").Batch
    cfg = FakeBatchConfig()
    batch = fake_batch(cfg, batch_size=4)
    assert isinstance(batch, Batch)
    validate_batch(batch, cfg)


def test_same_seed_same_batch():
    cfg = FakeBatchConfig()
    a = fake_batch_tensors(cfg, 4, seed=3)
    b = fake_batch_tensors(cfg, 4, seed=3)
    assert all(torch.equal(a[k], b[k]) for k in a)


def test_padding_appears_when_sizes_vary():
    cfg = FakeBatchConfig(min_cards=1, max_cards=6, min_actions=1, max_actions=5)
    t = fake_batch_tensors(cfg, batch_size=16, seed=0)
    assert not t["card_mask"].all()
    assert not t["action_mask"].all()


def test_no_padding_when_sizes_are_fixed():
    cfg = FakeBatchConfig(min_cards=4, max_cards=4, min_abilities=1, max_abilities=1, min_actions=3, max_actions=3)
    t = fake_batch_tensors(cfg, batch_size=5, seed=0)
    assert t["card_mask"].all() and t["ability_mask"].all() and t["action_mask"].all()
    assert t["card_ids"].shape == (5, 4) and t["active_edges"].shape[-1] == 1 + 4 + 1


def test_validator_catches_a_broken_batch():
    cfg = FakeBatchConfig()
    t = fake_batch_tensors(cfg, batch_size=8, seed=0)
    t["label"] = t["action_mask"].sum(dim=1)  # one past the last real action
    with pytest.raises(AssertionError):
        validate_batch(t, cfg)
