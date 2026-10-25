"""

Batch contract

V = vocabulary (DSK cards, DSK abilities)
N = visible cards
N_a = abilities
F = card instance state dimensions
F_a = ability instance state dimensions
M = N + N_a + 1 (visible cards + abilities + global state)
K = global board state dimensions
A = number of legal actions
G = global state dims

Example (of a batch B): 
* entity_id = position in M: [global_state (1), cards (N), abilities (N_a)]

- visible cards & abilities
    - card ids (B, N) -> long: padded up to N, visible cards' ids
    - card features (B, N, F) -> float32: padded up to N, visible card ids with their current state
    - ability ids (B, N_a) -> long : padded up to N_a, all DSK abilities' ids
    - ability features (B, N_a, F_a) -> float32: all DSK abilities on stack, padded up to N_a
- global_state (B, G) -> float32 -> which step (TARGETING), life totals, opp hand count
- active edges (B, E, M, M) -> bool: Edge-type -> from_entity_id -> to_entity_id
- legal action types (B, A) -> long: padded up to A, with action type
- legal action sources (B, A) -> long: padded up to A, with source entity_id
- legal action targets (B, A) -> long: padded up to A, with target entity_id
- legal action abilities (B, A) -> long: padded up to A, with ability_id

Masks & Padding
- use 0 as the sentinel across all features with embeddings; idx features use -1. Pad via sentinel
- action mask (B, A) -> bool
- card mask (B, N) -> bool: mask for cards, not card features.
- ability mask (B, N_a) -> bool: mask for abilities, not ability features.

Label
- chosen action (B,)
    

Hyperparameters:

D = attention hidden dimensions
D_c = card embeddings dimensions
D_a = action type embeddings dimensions

"""

from dataclasses import dataclass
from torch import Tensor

@dataclass
class Batch:
    card_ids: Tensor
    ability_ids: Tensor
    card_features: Tensor # (B, N, F) -> float32
    ability_features: Tensor # (B, N_a, F) -> float32

    global_state: Tensor # (B, G)
    active_edges: Tensor

    action_types: Tensor
    action_sources: Tensor
    action_targets: Tensor
    action_abilities: Tensor
    action_target_players: Tensor # (B, 2)
    action_choices: Tensor # (B, 2)

    card_mask: Tensor # (B, N)
    ability_mask: Tensor # (B, N_a)
    action_mask: Tensor # (B, A)

    label: Tensor # (B)
