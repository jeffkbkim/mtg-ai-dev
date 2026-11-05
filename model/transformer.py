import torch
from torch import nn

class Transformer(nn.Module):
    def __init__(self, num_blocks: int, d_h: int, d_ff: int, num_heads: int = 1) -> None:
        
        super().__init__()
        self.blocks = nn.ModuleList([
            TransformerBlock(num_heads, d_h, d_ff) for _ in range(num_blocks)
        ])
        self.rms = nn.RMSNorm(normalized_shape=d_h)

    def forward(self, x: torch.Tensor, bias: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        stream = x
        for block in self.blocks:
            stream = block(stream, bias, mask)
        return self.rms(stream)


class TransformerBlock(nn.Module):
    def __init__(self, num_heads: int, d_h: int, d_ff: int) -> None:
        super().__init__()
        self.pre_attention_norm = nn.RMSNorm(normalized_shape=d_h, eps=1e-5)
        self.attention = Attention(d_h, num_heads)
        self.pre_ffn = nn.RMSNorm(normalized_shape=d_h, eps=1e-5)
        self.ffn = FFN(d_h, d_ff)

    def forward(self, x: torch.Tensor, bias: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        h = x + self.attention(self.pre_attention_norm(x), bias, mask)
        return h + self.ffn(self.pre_ffn(h))

class Attention(nn.Module):
    def __init__(self, d_h: int, num_heads: int) -> None:
        assert num_heads == 1
        super().__init__()
        self.d_h = d_h

        self.Q = nn.Linear(d_h, d_h)
        self.K = nn.Linear(d_h, d_h)
        self.V = nn.Linear(d_h, d_h)
        self.O = nn.Linear(d_h, d_h)

    def forward(self, x: torch.Tensor, bias: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        # x: (B, M, D), bias: (B, M, M), mask: (B, M)
        q_proj = self.Q(x) # (B, M, D)
        k_proj = self.K(x) # (B, M, D)
        v_proj = self.V(x) # (B, M, D)

        raw_attention_score = (q_proj @ k_proj.transpose(-1, -2)) / self.d_h ** 0.5 # (B, M, M)

        edge_aware_attention_score = raw_attention_score + bias
        score = edge_aware_attention_score.masked_fill(
            ~mask.unsqueeze(dim=-2), float('-inf')
        )
        return self.O(nn.functional.softmax(score, dim=-1) @ v_proj) # (B, M, D)

class FFN(nn.Module):
    def __init__(self, d_h: int, d_ff: int) -> None:
        super().__init__()

        self.gate = nn.Linear(d_h, d_ff)
        self.up = nn.Linear(d_h, d_ff)
        self.down = nn.Linear(d_ff, d_h)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        gated = nn.functional.silu(self.gate(x))
        up_proj = self.up(x)

        return self.down(gated * up_proj)