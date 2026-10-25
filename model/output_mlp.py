import torch
from torch import nn

class OutputMLP(nn.Module):
    def __init__(self, input_features: int, output_features: int) -> None:
        super().__init__()
        self.input_layer = nn.Linear(input_features, output_features)
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(p=0.2)
        self.output_layer = nn.Linear(output_features, 1, bias=False)

    def forward(self, x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        print(x.shape, self.input_layer.weight.shape)
        values = self.output_layer(self.dropout(self.relu(self.input_layer(x)))).squeeze(dim=-1)
        values[~mask] = float('-inf')
        print("final values:", values)
        return values