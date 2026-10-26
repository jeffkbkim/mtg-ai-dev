"""Sizes every batch has to agree on: vocabulary sizes and feature widths.

Real and fake batches both need these, and so does the model (embedding tables, input Linears).
Build them in one place so the encoder, the validator and the model can't drift apart:

    cfg = BatchConfig.from_vocab()     # real XMage data: sizes from the vocab and engine/encode.py
    cfg = FakeBatchConfig()            # fake data: small sizes plus generator settings (synthetic/fake_batch.py)
"""

from dataclasses import dataclass


@dataclass
class BatchConfig:
    # Vocabulary sizes, including id 0 = PAD. Real ids are 1 .. vocab - 1.
    vocab_card: int
    vocab_ability: int
    vocab_action: int
    vocab_choice: int  # named choices (alt cost, modes); 0 = not a choice
    # Feature widths
    card_feature_dim: int  # F
    ability_feature_dim: int  # F_a
    global_state_dim: int  # K
    num_edge_types: int  # E

    @classmethod
    def from_vocab(cls, vocab=None) -> "BatchConfig":
        """The sizes of batches made by engine/encode.py's collate."""
        from engine.encode import (ABILITY_FEATURES, ACTION_TYPES, CARD_FEATURES, EDGE_TYPES, GLOBAL_FEATURES,
                                   Vocab)
        vocab = vocab or Vocab.load()
        return cls(
            vocab_card=vocab.num_cards,
            vocab_ability=vocab.num_abilities,
            vocab_action=len(ACTION_TYPES),
            vocab_choice=vocab.num_choices,
            card_feature_dim=len(CARD_FEATURES),
            ability_feature_dim=len(ABILITY_FEATURES),
            global_state_dim=len(GLOBAL_FEATURES),
            num_edge_types=len(EDGE_TYPES),
        )
