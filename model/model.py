"""

"""

from dataclasses import dataclass

import torch
from torch import nn

from model.batch import Batch
from model.output_mlp import OutputMLP
from model.transformer import Transformer

EMB_PAD = 0

@dataclass
class ModelConfig:
        emb_dim: int
        feature_dim: int
        vocab_card: int
        vocab_ability: int
        vocab_actions: int
        global_state_dim: int
        hidden_dim: int
        ffn_dim: int
        num_edges: int


class Model(nn.Module):
    def __init__(self, 
        emb_dim: int,
        feature_dim: int,
        vocab_card: int, 
        vocab_ability: int,
        vocab_actions: int,
        global_state_dim: int,
        hidden_dim: int,
        ffn_dim: int,
        num_edges: int
    ) -> None:
        
        self.model_config = ModelConfig(
             emb_dim,
             feature_dim,
             vocab_card,
             vocab_ability,
             vocab_actions,
             global_state_dim,
             hidden_dim,
             ffn_dim,
             num_edges
        )

        super().__init__()
        self.card_embeddings = nn.Embedding(vocab_card, emb_dim)
        self.ability_embeddings = nn.Embedding(vocab_ability, emb_dim)
        self.entity_linear = nn.Linear(emb_dim + feature_dim, hidden_dim)
        self.global_linear = nn.Linear(global_state_dim, hidden_dim)

        self.transformer = Transformer(num_blocks=1, d_h=hidden_dim, d_ff=ffn_dim)
        self.edge_w = nn.Parameter(torch.zeros(num_edges))

        self.action_embeddings = nn.Embedding(vocab_actions, emb_dim)
        self.final_mlp = OutputMLP(
            input_features=3 * hidden_dim + 2 * emb_dim, 
            output_features=hidden_dim
        )


    def forward(self, batch: Batch) -> torch.Tensor:
        B, A = batch.action_types.shape

        card_embs = torch.cat((self.card_embeddings(batch.card_ids), batch.card_features), dim=-1) # (B, N, De + F)
        ability_embs = torch.cat((self.ability_embeddings(batch.ability_ids), batch.ability_features), dim=-1) # (B, N_a, De + F)

        cards_abilities = torch.cat((card_embs, ability_embs), dim=-2) # (B, N+N_a, D_e + F)
        cards_abilities_hidden = self.entity_linear(cards_abilities) # (B, N+N_a, D)
        global_hidden = self.global_linear(batch.global_state).unsqueeze(dim=-2) # (B, 1, D)
        entities = torch.cat((global_hidden, cards_abilities_hidden), dim=-2) # (B, M, D)
        bias = torch.einsum("beij,e->bij", batch.active_edges.float(), self.edge_w) # (B, M, M)

        attention_mask = torch.cat((torch.ones(B, 1, dtype=torch.bool), batch.card_mask, batch.ability_mask), dim=-1)
        scaled_attention = self.transformer(entities, bias, attention_mask)

        print("scaled_attn", scaled_attention.shape)

        action_embs = self.action_embeddings(batch.action_types) # (B, A, D_e)
        action_ability = self.ability_embeddings(batch.action_abilities) # (B, A, D_e)
        action_source_mask = torch.where(batch.action_sources >= 0, batch.action_sources, 0) # (B, A)
        action_target_mask = torch.where(batch.action_targets >= 0, batch.action_targets, 0) # (B, A)
        batch_idx = torch.arange(B, device=scaled_attention.device).unsqueeze(dim=-1) # (B, 1)
        attended_action_source = scaled_attention[batch_idx, action_source_mask, :] # (B, A, D)
        attended_action_target = scaled_attention[batch_idx, action_target_mask, :] # (B, A, D)
        attended_global_state = scaled_attention[batch_idx, 0, :].expand(-1, A, -1) # (B, 1, D) -> (B, A, D)

        source_valid = batch.action_sources >= 0 # (B, A)
        target_valid = batch.action_targets >= 0 # (B, A)
        masked_action_source = attended_action_source * source_valid.unsqueeze(dim=-1) # (B, A, D)
        masked_action_target = attended_action_target * target_valid.unsqueeze(dim=-1) # (B, A, D)

        context_aware_actions = torch.cat(
            (
                action_embs, # D_e
                masked_action_source, # D
                masked_action_target, # D
                action_ability, # D_e
                attended_global_state # D
            ), dim=-1
        ) # (B, A, 3D + 2D_e)

        print("context aware actions", context_aware_actions.shape)

        # mask = batch.action_types >= 0

        # print("action types", )
        # print("mask", mask)
        return self.final_mlp(context_aware_actions, batch.action_mask)

    def config(self):
        return self.model_config




        




        

