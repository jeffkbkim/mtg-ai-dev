# MTG AI

A learning project: design and train an MTG gameplay model, starting with Duskmourn: House of Horror (DSK) Limited.

## Goals

- Learn representation design, neural architectures, training and evaluation by implementing the model ourselves.
- Eventually draft, build a deck, and play against the agent in a usable interface.
- Start with gameplay; add drafting later. Start with DSK; additional historical draft formats are optional.

## Initial approach

Reuse a rules engine, tentatively XMage, and integration/data tools where suitable. Train our own Python/PyTorch model from random weights. Initially choose legal actions directly without decision-time search. Compare a simple model against entity attention and graph models through controlled experiments.

The agent receives only information available to its seat. Opponent hands, hidden face-down identities and future library order must not leak into observations.

## Working across environments

Use separate clones on the Mac and cloud machines. Start each task from updated main, work on separate branches, and commit/push before switching environments. Keep datasets, credentials and checkpoints out of Git.

See [the plan](docs/plan.md), [decisions](docs/decisions.md) and [Codex instructions](AGENTS.md). No engine integration or training is implemented yet.
