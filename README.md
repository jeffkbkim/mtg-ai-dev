# MTG AI

A self-directed project to build and train a Magic: The Gathering gameplay agent from scratch, starting with
Duskmourn: House of Horror (DSK) Limited. It reuses a rules engine (XMage) and public 17lands data; the observation
format, data pipeline, evaluation tooling and model are our own.

Started 2026-10-07. Built by Jeff Kim, with AI coding assistants doing most of the engine integration, data and
tooling work under his direction. Model design and model code are Jeff's own; [AGENTS.md](AGENTS.md) sets that split.

## What's built and what's been measured

**Engine integration with hidden-information checks** (`engine/xmage/`)
- XMage 1.4.62 release jars plus our own Java seat classes hand every real decision to Python as JSON, with an
  observation built from that seat's view only.
- Every message is checked against the full game state for leaks of opponent hands, face-down identities and future
  draws: 0 leaks over the first 50+ recorded games, planted leaks caught.
- A 2,318-game coverage soak (random seat vs XMage's AI) put every non-basic DSK card into play at least once and
  found real bugs, each now fixed with a check that fails before and passes after
  ([results](experiments/coverage_soak/results-2026-10-20.md)):
  - a real leak: on opponent-paid discard costs, our seat chose from the *other* player's hand;
  - XMage's AI simulating moves on copies of the game that still asked our Python seat about boards that never happened;
  - an XMage `CrewCost` bug that let a vehicle count toward its own Crew.
- A second set, Foundations (FDN), ran 968 soak games that all finished; the issues found were fixed or logged as
  open ([results](experiments/coverage_soak/results-2026-10-28-fdn.md)).

**Training data from real games** (`seventeenlands/`)
- 17lands DSK Premier Draft data: 1,011,949 games and replays, 7.08M picks, audited and split by draft with a
  frozen hash, so every pick, game and replay of a draft lands in the same split.
- 17lands records what was played each turn, not when, targets, or who blocked whom. `turn_replay.py` replays each
  game in XMage turn by turn and searches the missing choices with XMage's rollback
  ([write-up](seventeenlands/TURN_REPLAY.md)).
- 50,000-game run (41 hours on a Mac mini): 76.2% of turns reproduce the recorded end of turn from an exact start,
  89.5% before a game's first miss. That produced 4,456,698 decision rows, each labelled exact (89.3%), uniquely
  inferred (3.0%) or ambiguous (7.5%).

**Claude as a player, and evaluating it** (`play/`)
- A Claude player plays through the same leak-checked observation and records every decision with its reason,
  tokens, cost and a prompt hash, so games from different prompts are never pooled.
- Prompt changes are tested on frozen decisions before rollout: on 19 recorded positions (9 known mistakes,
  10 controls the old prompt got right, 3 samples each), primer v2 fixed 3 of the 9 mistakes and broke none of the
  controls ([notes](notes/puzzles-v1-vs-v2-2026-10-24.md)).
- An LLM deck reviewer was checked for bias by regressing its ratings on card quality and drafter skill over
  363 decks. It under-rated blue-green (residual -0.34 ± 0.06) and manifest-dread decks (-0.24 ± 0.05), mostly
  for "few creatures". A revised prompt that counts tokens, manifest and recursion as bodies moved those decks
  +0.15 on a held-out set ([results](experiments/reviewer_bias/results.md)).
- Playmat (`engine/playmat/`): play against the agent, or watch it, in a browser; a Quick Draft mode drafts
  against 7 bots. Every game is recorded in the same decision format.

**Model** (`model/`, `engine/encode.py`, `engine/dataset.py`)
- v1 policy: card entities plus a global-state entry go through a transformer block whose attention gets a learned
  bias per engine-supplied relation (blocks, attached to, resolves before, ...). Each legal action is scored from its
  source, target, global and action-type slots, and a softmax runs over the legal options. Design notes are in
  [docs/decisions.md](docs/decisions.md).
- It passes the overfit-one-batch test. The dataset builder caches replay chunks and streams them to training.
- Imitation training of the policy on the replay rows has started (policy head only, no results yet).
- Claude-vs-Claude games are being generated as a second data source, recorded with model, effort and prompt hash.

## Not done yet

- No playing-strength results yet. The policy will be evaluated in real games against fixed opponents with seat
  balance and uncertainty intervals, not by move agreement.
- Planned next: a value head, then MCTS, then reinforcement learning with an opponent pool. Drafting comes after
  gameplay.

## Layout

| Path | What |
|---|---|
| `engine/xmage/` | Java seats, match runners, rules checks (`*Check.java`), deck pools |
| `engine/encode.py`, `engine/dataset.py` | decisions to tensors; dataset build and streaming |
| `engine/playmat/` | browser play: a patch series on a pinned Playmat commit, plus our seat plugin |
| `seventeenlands/` | 17lands download audit, split, turn replay, decision export |
| `play/` | Claude player, game and deck reviewers, A/B tooling, frozen-decision puzzles |
| `model/` | policy model |
| `experiments/` | soaks, engine smoke tests, reviewer bias, latency studies |
| `docs/` | [plan](docs/plan.md), [decisions](docs/decisions.md), research notes |

## Setup

Python dependencies are managed with [uv](https://docs.astral.sh/uv/). `pyproject.toml`, `uv.lock` and `.python-version` (3.12) are committed; `.venv/` is not.

```bash
uv sync                   # create .venv from the lockfile (installs Python 3.12 if needed)
uv run pytest             # run tests inside the venv
uv add <package>          # add a dependency and update uv.lock
```

The PyPI `torch` wheel supports MPS on Apple Silicon and CUDA on Linux, so the same lockfile works on the Mac and on rented GPU machines.

Large data, checkpoints and recordings live outside Git (under `~/mtg-data/` on the machine that made them).

## Working across environments

Use separate clones on the Mac and cloud machines. While prototyping, work directly on main; pull before starting and commit/push before switching environments. Keep datasets, credentials and checkpoints out of Git.
