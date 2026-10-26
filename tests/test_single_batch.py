"""Overfit one batch: the first end-to-end check of the model.

Run:
    uv run pytest tests/test_single_batch.py -s    # -s shows the loss curve
    uv run python -m tests.test_single_batch       # same thing as a script

Two tests, same checks:
- test_overfit_one_batch: a fake batch (small vocab, random labels).
- test_overfit_one_batch_real: 8 real XMage decisions from tests/fixtures, sizes from the vocab.

What it checks, in order:
1. The output is (B, A) raw logits, with padded actions at -inf and real actions finite.
2. Loss at step 0 is near the "uniform guess" loss, mean(log(number of legal actions)).
   Printed only: a big gap means the initial logits are large, worth a look but not a bug.
3. Every parameter gets a gradient on the first backward pass (all-zero gradients are printed, not failed).
4. Training on one fixed batch of 8 drives loss to ~0 and accuracy to 100%.

With 8 examples and enough steps, the only way to pass 4 is to memorize them.
If the model can't do that, something is wired wrong (a mask, a gather, a detached
tensor, the learning rate), and more data won't fix it.

Edit build_model() when your Model's constructor changes.
"""

from pathlib import Path

import pytest
import torch
import torch.nn.functional as F

from engine.batch_config import BatchConfig
from synthetic.fake_batch import FakeBatchConfig, fake_batch, validate_batch

REAL_DECISIONS = Path(__file__).parent / "fixtures" / "xmage_decisions_sample.jsonl"

BATCH_SIZE = 8
STEPS = 500
LR = 1e-3
SEED = 0
LOG_EVERY = 25
PASS_LOSS = 0.01

# One config for both the data and the model, so vocab sizes and widths always agree.
# Your Model sends card and ability features through one Linear, so F == F_a here.
CFG = FakeBatchConfig(card_feature_dim=5, ability_feature_dim=5)


def build_model(cfg: BatchConfig):
    from model.model import Model

    return Model(
        emb_dim=16,  # different from hidden_dim on purpose, so a width mix-up shows up as an error
        feature_dim=cfg.card_feature_dim,
        vocab_card=cfg.vocab_card,
        vocab_ability=cfg.vocab_ability,
        vocab_actions=cfg.vocab_action,
        global_state_dim=cfg.global_state_dim,
        hidden_dim=32,
        ffn_dim=64,
        num_edges=cfg.num_edge_types,
    )


def check_logits(logits: torch.Tensor, batch) -> None:
    B, A = batch.action_mask.shape
    assert logits.shape == (B, A), f"output shape {tuple(logits.shape)}, expected (B, A) = {(B, A)}"
    real = logits[batch.action_mask]
    assert torch.isfinite(real).all(), "real actions must have finite logits (found inf or NaN)"
    assert (logits[~batch.action_mask] == float("-inf")).all(), "padded actions must have logit -inf"
    rows = logits.masked_fill(~batch.action_mask, 0)
    looks_like_probs = (real >= 0).all() and (real <= 1).all() and torch.allclose(rows.sum(-1), torch.ones(B))
    assert not looks_like_probs, "output looks like probabilities; F.cross_entropy wants raw logits (no softmax)"


def check_gradients(model) -> None:
    missing = [name for name, p in model.named_parameters() if p.requires_grad and p.grad is None]
    zero = [name for name, p in model.named_parameters() if p.grad is not None and not p.grad.any()]
    assert not missing, f"parameters with no gradient (not used, or detached): {missing}"
    if zero:
        # Printed, not failed: some zeros are expected. The last layer's bias adds the same
        # number to every action's score, and softmax ignores a shift shared by all actions,
        # so its gradient is exactly 0. Anything else in this list is worth a look.
        print(f"note: parameters whose gradient is all zeros: {zero}")


def overfit(model, batch, steps: int = STEPS, lr: float = LR, log=print) -> tuple[float, float]:
    model.eval()  # turns dropout off; gradients still flow
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss = acc = None
    for step in range(steps + 1):
        logits = model(batch)
        loss = F.cross_entropy(logits, batch.label)
        acc = (logits.argmax(dim=-1) == batch.label).float().mean().item()
        assert torch.isfinite(loss), f"loss is {loss.item()} at step {step}"

        if step == 0:
            check_logits(logits, batch)
            uniform = batch.action_mask.sum(dim=1).float().log().mean().item()
            log(f"step 0: loss {loss.item():.4f}, uniform guess {uniform:.4f}"
                + ("" if abs(loss.item() - uniform) < 0.5 else "  <- far apart: large initial logits?"))
        elif step % LOG_EVERY == 0:
            log(f"step {step:4d}: loss {loss.item():.4f}  accuracy {acc:.2f}")
        if step == steps or (loss.item() < PASS_LOSS and acc == 1.0):
            break

        opt.zero_grad()
        loss.backward()
        if step == 0:
            check_gradients(model)
        opt.step()
    log(f"stopped at step {step}: loss {loss.item():.4f}  accuracy {acc:.2f}")
    return loss.item(), acc


def overfit_one_batch(batch, cfg: BatchConfig) -> None:
    validate_batch(batch, cfg)
    model = build_model(cfg)
    B, A = batch.action_mask.shape
    print(f"\n{sum(p.numel() for p in model.parameters()):,} parameters, "
          f"{B} examples, A = {A}, "
          f"legal actions per example {batch.action_mask.sum(dim=1).tolist()}")
    loss, acc = overfit(model, batch)
    assert acc == 1.0 and loss < PASS_LOSS, (
        f"did not memorize one batch: loss {loss:.4f}, accuracy {acc:.2f} after {STEPS} steps")


def test_overfit_one_batch():
    pytest.importorskip("model.model")  # skipped where model/ isn't checked in
    torch.manual_seed(SEED)
    overfit_one_batch(fake_batch(CFG, BATCH_SIZE, seed=SEED), CFG)


def test_overfit_one_batch_real():
    pytest.importorskip("model.model")
    from engine.encode import Vocab, collate, encode_file
    from model.batch import Batch

    torch.manual_seed(SEED)
    vocab = Vocab.load()
    examples, problems = encode_file(REAL_DECISIONS, vocab)
    assert not problems, f"decisions the encoder couldn't map: {problems}"
    batch = Batch(**collate(examples[:BATCH_SIZE]))
    overfit_one_batch(batch, BatchConfig.from_vocab(vocab))


if __name__ == "__main__":
    test_overfit_one_batch()
    test_overfit_one_batch_real()
    print("PASS")
