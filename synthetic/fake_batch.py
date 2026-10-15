"""Random batches that follow the batch contract in model/batch.py.

Use these to run the model on fake data before the XMage adapter exists:
shape tests, padding tests, loss at init, and overfitting one batch.

Layout of the M entries in every example (entity id = position in M):

    [ global (1) | cards (N) | abilities on the stack (N_a) ]
      index 0      1 .. N      N+1 .. N+N_a

N, N_a and A are the largest counts in the batch. Smaller examples are padded:
- vocab id fields (card_ids, ability_ids, action_types, action_abilities, action_choices): 0
- entry index fields (action_sources, action_targets): -1
- action_target_players: 0 (1 = me, 2 = opponent, only on actions with no target entry)
- float fields: 0.0
- masks: True = real, False = padding

The labels are random, so there is nothing to learn beyond memorizing. That is
enough for "overfit one batch". Rules with a known answer come later.

Usage:
    cfg = FakeBatchConfig()
    batch = fake_batch(cfg, batch_size=4, seed=0)   # your Batch dataclass
    tensors = fake_batch_tensors(cfg, 4, seed=0)    # plain dict with every field
    validate_batch(batch, cfg)                       # raises if the contract is broken
"""

from dataclasses import dataclass, fields

import torch
from torch import Tensor

PAD_ID = 0  # vocab id fields
EMPTY_IDX = -1  # entry index fields


@dataclass
class FakeBatchConfig:
    # Vocabulary sizes, including id 0 = PAD. Real ids are 1 .. vocab - 1.
    vocab_card: int = 20
    vocab_ability: int = 10
    vocab_action: int = 6
    vocab_choice: int = 4  # named choices (alt cost, modes); 0 = not a choice
    # Feature widths
    card_feature_dim: int = 5  # F
    ability_feature_dim: int = 5  # F_a
    global_state_dim: int = 7  # K
    num_edge_types: int = 3  # E
    # Per-example counts are drawn uniformly from [min, max]
    min_cards: int = 1
    max_cards: int = 6
    min_abilities: int = 0
    max_abilities: int = 2
    min_actions: int = 1
    max_actions: int = 5
    # Chance that an edge exists between two real entries, per edge type
    edge_prob: float = 0.15
    # Chance that a real action has a source / target / ability
    source_prob: float = 0.7
    target_prob: float = 0.5
    ability_prob: float = 0.3
    # Chance that a real action with no target entry targets a player instead
    player_target_prob: float = 0.4
    # Chance that a real action carries a named choice
    choice_prob: float = 0.2


def fake_batch_tensors(cfg: FakeBatchConfig, batch_size: int, seed: int = 0) -> dict[str, Tensor]:
    """Every contract field, including masks and label, as a dict of CPU tensors."""
    g = torch.Generator().manual_seed(seed)

    def randint(low: int, high: int, size=()) -> Tensor:
        # inclusive of both ends
        return torch.randint(low, high + 1, size, generator=g)

    B = batch_size
    n = randint(cfg.min_cards, cfg.max_cards, (B,))
    n_a = randint(cfg.min_abilities, cfg.max_abilities, (B,))
    a = randint(cfg.min_actions, cfg.max_actions, (B,))
    N, N_a, A = int(n.max()), int(n_a.max()), int(a.max())
    M = 1 + N + N_a

    card_mask = torch.arange(N) < n[:, None]  # (B, N)
    ability_mask = torch.arange(N_a) < n_a[:, None]  # (B, N_a)
    action_mask = torch.arange(A) < a[:, None]  # (B, A)

    card_ids = randint(1, cfg.vocab_card - 1, (B, N)) * card_mask
    ability_ids = randint(1, cfg.vocab_ability - 1, (B, N_a)) * ability_mask
    card_features = torch.randn(B, N, cfg.card_feature_dim, generator=g) * card_mask[..., None]
    ability_features = torch.randn(B, N_a, cfg.ability_feature_dim, generator=g) * ability_mask[..., None]
    global_state = torch.randn(B, cfg.global_state_dim, generator=g)

    # Which of the M entries are real, in entry order [global | cards | abilities]
    entry_mask = torch.cat((torch.ones(B, 1, dtype=torch.bool), card_mask, ability_mask), dim=1)  # (B, M)

    # Edges only between two real entries, never from an entry to itself
    real_pair = entry_mask[:, :, None] & entry_mask[:, None, :] & ~torch.eye(M, dtype=torch.bool)
    active_edges = (torch.rand(B, cfg.num_edge_types, M, M, generator=g) < cfg.edge_prob) & real_pair[:, None]

    action_types = randint(1, cfg.vocab_action - 1, (B, A)) * action_mask

    # Sources point at a real card entry (1 .. n). Targets point at a real card or ability entry.
    card_entry = 1 + (torch.rand(B, A, generator=g) * n[:, None]).long()  # (B, A) in 1 .. n
    has_source = (torch.rand(B, A, generator=g) < cfg.source_prob) & action_mask
    action_sources = torch.where(has_source, card_entry, EMPTY_IDX)

    real_entries = n + n_a  # cards + abilities, excluding global
    k = (torch.rand(B, A, generator=g) * real_entries[:, None]).long()  # 0 .. n + n_a - 1
    target_entry = torch.where(k < n[:, None], 1 + k, 1 + N + (k - n[:, None]))  # skip padded card slots
    has_target = (torch.rand(B, A, generator=g) < cfg.target_prob) & action_mask
    action_targets = torch.where(has_target, target_entry, EMPTY_IDX)

    has_ability = (torch.rand(B, A, generator=g) < cfg.ability_prob) & action_mask
    action_abilities = randint(1, cfg.vocab_ability - 1, (B, A)) * has_ability

    label = (torch.rand(B, generator=g) * a).long()  # 0 .. a - 1

    # Drawn after everything else so the fields above stay the same for a given seed
    player = randint(1, 2, (B, A))  # 1 = me, 2 = opponent
    has_player = (torch.rand(B, A, generator=g) < cfg.player_target_prob) & action_mask & ~has_target
    action_target_players = player * has_player
    has_choice = (torch.rand(B, A, generator=g) < cfg.choice_prob) & action_mask
    action_choices = randint(1, cfg.vocab_choice - 1, (B, A)) * has_choice

    return {
        "card_ids": card_ids,
        "ability_ids": ability_ids,
        "card_features": card_features,
        "ability_features": ability_features,
        "global_state": global_state,
        "active_edges": active_edges,
        "action_types": action_types,
        "action_sources": action_sources,
        "action_targets": action_targets,
        "action_abilities": action_abilities,
        "action_target_players": action_target_players,
        "action_choices": action_choices,
        "card_mask": card_mask,
        "ability_mask": ability_mask,
        "action_mask": action_mask,
        "label": label,
    }


def fake_batch(cfg: FakeBatchConfig, batch_size: int, seed: int = 0):
    """A Batch with whichever contract fields the Batch dataclass currently declares."""
    from model.batch import Batch  # imported here so the generator and validator work without model/
    tensors = fake_batch_tensors(cfg, batch_size, seed)
    names = [f.name for f in fields(Batch)]
    missing = [name for name in names if name not in tensors]
    if missing:
        raise KeyError(f"Batch declares fields the generator doesn't make: {missing}")
    return Batch(**{name: tensors[name] for name in names})


def validate_batch(batch, cfg: FakeBatchConfig | None = None) -> None:
    """Check a batch against the contract. Works on a Batch or a dict; skips fields that aren't there.

    Raises AssertionError with the first broken rule.
    """
    get = batch.get if isinstance(batch, dict) else lambda name: getattr(batch, name, None)

    card_ids, ability_ids = get("card_ids"), get("ability_ids")
    B, N = card_ids.shape
    N_a = ability_ids.shape[1]
    M = 1 + N + N_a
    A = get("action_types").shape[1]

    def check(name: str, shape: tuple, dtype: torch.dtype) -> Tensor | None:
        t = get(name)
        if t is None:
            return None
        assert t.dtype == dtype, f"{name}: dtype {t.dtype}, expected {dtype}"
        assert tuple(t.shape) == shape, f"{name}: shape {tuple(t.shape)}, expected {shape}"
        return t

    F = get("card_features").shape[-1]
    F_a = get("ability_features").shape[-1]
    K = get("global_state").shape[-1]
    E = get("active_edges").shape[1]

    check("card_ids", (B, N), torch.long)
    check("ability_ids", (B, N_a), torch.long)
    card_features = check("card_features", (B, N, F), torch.float32)
    ability_features = check("ability_features", (B, N_a, F_a), torch.float32)
    check("global_state", (B, K), torch.float32)
    edges = check("active_edges", (B, E, M, M), torch.bool)
    action_types = check("action_types", (B, A), torch.long)
    sources = check("action_sources", (B, A), torch.long)
    targets = check("action_targets", (B, A), torch.long)
    abilities = check("action_abilities", (B, A), torch.long)
    players = check("action_target_players", (B, A), torch.long)
    choices = check("action_choices", (B, A), torch.long)
    card_mask = check("card_mask", (B, N), torch.bool)
    ability_mask = check("ability_mask", (B, N_a), torch.bool)
    action_mask = check("action_mask", (B, A), torch.bool)
    label = check("label", (B,), torch.long)

    if cfg is not None:
        assert card_ids.min() >= 0 and card_ids.max() < cfg.vocab_card, "card_ids outside vocab"
        assert ability_ids.min() >= 0 and ability_ids.max() < cfg.vocab_ability, "ability_ids outside vocab"
        assert action_types.min() >= 0 and action_types.max() < cfg.vocab_action, "action_types outside vocab"
        assert abilities.min() >= 0 and abilities.max() < cfg.vocab_ability, "action_abilities outside vocab"
        if choices is not None:
            assert choices.min() >= 0 and choices.max() < cfg.vocab_choice, "action_choices outside vocab"

    # Masks: real ids are non-zero, padding is 0 everywhere
    if card_mask is not None:
        assert ((card_ids != PAD_ID) == card_mask).all(), "card_ids: PAD (0) must be exactly where card_mask is False"
        assert (card_features[~card_mask] == 0).all(), "card_features: padded cards must be 0"
    if ability_mask is not None:
        assert ((ability_ids != PAD_ID) == ability_mask).all(), "ability_ids: PAD (0) must be exactly where ability_mask is False"
        assert (ability_features[~ability_mask] == 0).all(), "ability_features: padded abilities must be 0"

    if action_mask is not None:
        assert action_mask.any(dim=1).all(), "every example needs at least one legal action"
        assert ((action_types != PAD_ID) == action_mask).all(), "action_types: PAD (0) must be exactly where action_mask is False"
        assert (sources[~action_mask] == EMPTY_IDX).all(), "action_sources: padded actions must be -1"
        assert (targets[~action_mask] == EMPTY_IDX).all(), "action_targets: padded actions must be -1"
        assert (abilities[~action_mask] == PAD_ID).all(), "action_abilities: padded actions must be 0"
        if players is not None:
            assert ((players >= 0) & (players <= 2)).all(), "action_target_players: must be 0 (none), 1 (me) or 2 (opp)"
            assert (players[~action_mask] == 0).all(), "action_target_players: padded actions must be 0"
            assert (players[targets != EMPTY_IDX] == 0).all(), "action_target_players: action has both a target entry and a player"
        if choices is not None:
            assert (choices[~action_mask] == PAD_ID).all(), "action_choices: padded actions must be 0"

    # Entry indices are -1 or point at a real entry
    if card_mask is not None and ability_mask is not None:
        entry_mask = torch.cat((torch.ones(B, 1, dtype=torch.bool), card_mask, ability_mask), dim=1)  # (B, M)
        for name, idx in (("action_sources", sources), ("action_targets", targets)):
            assert ((idx >= EMPTY_IDX) & (idx < M)).all(), f"{name}: index outside -1 .. M-1"
            pointed = entry_mask.gather(1, idx.clamp(min=0))
            assert (pointed | (idx == EMPTY_IDX)).all(), f"{name}: points at a padded entry"
        if edges is not None:
            real_pair = entry_mask[:, :, None] & entry_mask[:, None, :]
            assert not (edges & ~real_pair[:, None]).any(), "active_edges: edge touches a padded entry"

    if label is not None and action_mask is not None:
        assert ((label >= 0) & (label < A)).all(), "label outside 0 .. A-1"
        assert action_mask.gather(1, label[:, None]).all(), "label points at a padded action"
