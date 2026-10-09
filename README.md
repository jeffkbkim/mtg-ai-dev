# MTG AI

A learning project: design and train an MTG gameplay model, starting with Duskmourn: House of Horror (DSK) Limited.

## Goals

- Learn representation design, neural architectures, training and evaluation by implementing the model ourselves.
- Eventually draft, build a deck, and play against the agent in a usable interface.
- Start with gameplay; add drafting later. Start with DSK; additional historical draft formats are optional.

## Initial approach

Reuse a rules engine, tentatively XMage, and integration/data tools where suitable. Train our own Python/PyTorch model from random weights. Initially choose legal actions directly without decision-time search. Compare a simple model against entity attention and graph models through controlled experiments.

The agent receives only information available to its seat. Opponent hands, hidden face-down identities and future library order must not leak into observations.

## Setup

Python dependencies are managed with [uv](https://docs.astral.sh/uv/). `pyproject.toml`, `uv.lock` and `.python-version` (3.12) are committed; `.venv/` is not.

```bash
uv sync                   # create .venv from the lockfile (installs Python 3.12 if needed)
uv run pytest             # run tests inside the venv
uv add <package>          # add a dependency and update uv.lock
```

The PyPI `torch` wheel supports MPS on Apple Silicon and CUDA on Linux, so the same lockfile works on the Mac and on rented GPU machines.

## Working across environments

Use separate clones on the Mac and cloud machines. While prototyping, work directly on main; pull before starting and commit/push before switching environments. Keep datasets, credentials and checkpoints out of Git.

See [the plan](docs/plan.md), [decisions](docs/decisions.md) and [Codex instructions](AGENTS.md). No engine integration or training is implemented yet.
