# mtg-ai

A Magic: The Gathering gameplay agent for **Duskmourn: House of Horror (DSK) Limited**, trained from scratch in PyTorch.
The policy is a small transformer over the visible game state that scores the engine's legal actions directly.
It learns by imitation from human games: public 17lands game summaries, replayed turn by turn in the XMage rules engine
to recover decision-level labels. Next come a value head and search (MCTS), then self-play.

The project covers the whole loop: rules-engine integration with hidden-information checks, dataset construction from
lossy human records, model training, and evaluation in real games with confidence intervals. Results below are
reported as measured, including the ones that went badly.

## Current state (2026-11-12)

| | |
|---|---|
| Engine | XMage 1.4.62 release jars plus our own Java seat classes, driven from Python; every observation checked for hidden-information leaks |
| Data | 1.01M public 17lands DSK games; **200,000 replayed** in XMage so far into decision rows with exact / inferred / set labels (another 50k in progress) |
| Model (v1) | 1-layer transformer, 30.9k parameters, masked softmax over legal actions |
| Held-out agreement | **88.3%** top-1 on 146k test decisions (best non-learned baseline 77.4%) |
| Games | 36.2% vs a random bot, 8.2% vs XMage's AI (400 seat-balanced games each). **Worse than random**; cause found, fix in training |

Full numbers: [experiments/policy_v1/results.md](experiments/policy_v1/results.md).

## Architecture

The diagram of the v1 network with every tensor shape is in the [Model v1 artifact](https://claude.ai/artifact/EC4UACoAdXiiauQddMuAb4).
Code: [model/](model/), batch contract in [model/batch.py](model/batch.py), decision log in [docs/decisions.md](docs/decisions.md).

### What the network sees

A decision is a set of **entries**: `[global | cards | stack abilities]`.

- **Cards.** Every card the acting seat can see becomes one entry: a learned card embedding (DSK card names, tokens,
  and a single `FACE_DOWN` id for hidden face-down cards) concatenated with per-instance features (zone, tapped,
  power/toughness, counters, keywords, ...) and projected to width D.
- **Stack abilities.** Triggered and activated abilities on the stack are their own entries, from a stable ability
  vocabulary built by the engine adapter (XMage's runtime ability ids change per game).
- **Global.** Turn, step, decision kind, whose decision it is, life totals, zone sizes: projected to D and placed as
  entry 0.
- **Relations as edges.** Directed edges from the engine (`blocks`/`blocked_by`, `attached_to`/`has_attached`,
  `targets`/`targeted_by`, `resolves_before`/`resolves_after`) add a learned scalar per edge type to the attention
  score of that pair.

### Encoder and action scorer

- Pre-norm transformer blocks (RMSNorm, single-head attention with the edge bias, SwiGLU FFN), **no positional
  encoding**. The default is one layer.
- Each legal action is built from slots `[action type | source entry | target entry | ability | global entry]`.
  Source and target are gathered from the encoder output by index, so an action *points at* the card it uses.
  PASS-style actions still see the situation through the global slot.
- An MLP scores each action. Softmax runs over the legal actions only, trained with cross-entropy against the human choice.
- Compound actions are sequential steps: choose the spell, then each target, each with its own softmax over the
  engine's legal options for that step.

### Why this architecture

- **Board state is a set, not a sequence.** The number of visible cards varies (mean ~27, max ~70) and their order
  means nothing. Self-attention without positional encoding accepts any number of entries, is permutation-equivariant,
  and gives one output row per card for actions to point at. Flattened fixed-slot inputs, RNNs and CNNs impose an
  arbitrary order and were ruled out.
- **Relations matter but are sparse and typed.** Who blocks whom, what an Aura enchants and what a spell targets are
  known exactly from the engine, so they enter as explicit edge biases instead of being re-inferred from features.
  Stack order is a pair of edges, not a position feature.
- **The action space is open-ended.** Legal actions differ every decision, so the policy scores the engine's own
  legal list instead of a fixed output vocabulary. Pointing at card rows by index generalises across boards and
  needs no output vocabulary over card instances.
- **Start small and earn the complexity.** One layer, one head, width 16 to 32. Interaction (attention) is meant to
  be tested against a pooling (DeepSets) baseline and a relation network under equal budgets. Architecture choices
  are hypotheses to measure, not settled.

### Next: value head and search

- **Value head (in progress).** A win-probability head on the global entry's encoder output, trained on each game's
  17lands result, which is already joined into the dataset (`build-17lands --outcomes`; base rate 54.3% wins).
- **Search (planned).** PUCT-style MCTS with the policy as prior and the value head at the leaves, then search visit
  counts as policy targets and real results as value targets (search as teacher, then self-play). Magic needs more
  than board-game MCTS: hidden hands and libraries, several decisions in a row by the same player, and long chains
  of small priority decisions. An interactive walkthrough of the search, built for this project:
  [MCTS by Hand](https://claude.ai/artifact/FGoe49qtNsweZf5FCdghtm).
- The first player deliberately has no decision-time search, so search can later be measured as its own experiment.

## Data pipeline

```
17lands public DSK data (1.01M Premier Draft games, per-turn summaries)
  -> split frozen by draft_id (train 80 / val 10 / test 10; every pick, game and replay of a draft together)
  -> turn replay in XMage: rebuild each game, search the unrecorded choices with engine rollback
  -> decision rows: per-seat observation, legal options, label + how certain it is
  -> encoder (engine/encode.py) -> tensor cache -> training
```

- **Why replay at all.** 17lands records what each turn did (lands, casts, attacks, blockers, end-of-turn hands,
  boards and life), not the individual decisions. [seventeenlands/turn_replay.py](seventeenlands/turn_replay.py)
  replays each game in XMage with scripted seats. The missing details (timing window, targets, modes, block pairing,
  trigger order) become choice points, searched with XMage's rollback until the end of turn matches the record:
  **~90% of turns reproduce** before a game's first miss. Details and failure analysis:
  [seventeenlands/TURN_REPLAY.md](seventeenlands/TURN_REPLAY.md).
- **Labels carry their certainty.** `recorded` (the record decides it), `unique` (searched, and an ambiguity probe
  proved no other choice fits), `ambiguous_set` (every option consistent with the record) and `alternative`
  (decisions along the other readings of the turn, each reading weighted 1/n so a turn counts once).
- **Scale.** 200,000 games replayed so far in four 50k runs (~2.3M decision rows per run). The first three were
  re-replayed to add set labels. A fifth run is in progress.
- **Hidden information.** The seat only gets what that player could see. Every message is checked against the full
  game state for leaks of the opponent's hand, face-down identities and library order. Planted leaks are caught, and
  the checker found a real one: our seat was offered the opponent's hand when the opponent paid a discard cost
  (fixed, with a regression check).
- **Claude-played games.** A Claude player ([play/](play/)) plays DSK through the same seat and records every decision
  with its reasoning: 920 games so far, 618 clean after review. They serve as extra data and as a stronger
  opponent, and reviewing them found and fixed several engine and seat bugs.
- **Engine coverage.** A 2,318-game soak reached every non-basic DSK card at least once. Cards and abilities the
  encoder can't map are reported, never silently replaced ([experiments/coverage_soak/](experiments/coverage_soak/)).

## Evaluation

Two measurements, because agreement with humans is not playing strength
([experiments/policy_v1/](experiments/policy_v1/)):

1. **Held-out agreement** on the test split, overall and per decision kind, against random-legal and
   most-frequent-action baselines.
2. **Games** through an ONNX export of the policy (onnxruntime, greedy): 100 deck pairs of real 17lands decks, each
   played 4 times (each deck, on the play and on the draw). Wilson and deck-pair bootstrap 95% intervals. About 3 s
   per game on CPU.

### v1 baseline (checkpoint 200-l1)

| kind | n | random legal | most-frequent prior | policy |
|---|---:|---:|---:|---:|
| all | 146,211 | 42.8% | 77.4% | **88.3%** |
| PRIORITY | 97,589 | 42.6% | 86.4% | 93.3% |
| ATTACK | 21,420 | 43.4% | 54.1% | 78.2% |
| BLOCK | 5,561 | 40.2% | 60.6% | 68.1% |
| TARGET | 5,376 | 31.2% | 33.2% | 71.4% |

| seat A | vs | W-L | win rate (95% CI) |
|---|---|---:|---|
| policy | random bot | 145-255 | 36.2% (31.7-41.1) |
| policy | XMage AI | 33-367 | 8.2% (5.9-11.4) |
| random bot | XMage AI | 58-342 | 14.5% (11.4-18.3) |

**88% agreement, yet worse than random in games.** The policy skipped its first land drop in 64% of games and its
second in 40% (random bot: about 1%). The cause was in the data, not the network. A 17lands turn summary says a land was
played, not whether in the first or second main phase. Both readings reproduce the turn, so those decisions were
labelled ambiguous and dropped: about 97% of early land-drop decisions and most sorcery-speed casts. The passes that
survived were all certain, so the training set taught "pass in main phase 1".

**Fix (next training run).** No hand-written timing rule. The replay keeps every reading of an ambiguous turn: the set
of consistent options (`ambiguous_set`) plus the decisions along each other reading (`alternative`), trained with a
set-valued loss (maximise the probability mass on the consistent set). Success criteria, fixed in advance: early
land-drop misses near 1%, and a win rate above random with intervals that don't overlap, on the same seeds and deck pairs.

## Repository layout

| Path | What |
|---|---|
| `model/`, `training/` | Policy network, trainer, run comparison, TensorBoard metrics |
| `engine/xmage/` | Java seats and match runners on the XMage release jars, observation builder, leak checks, rule fixes |
| `engine/encode.py`, `engine/dataset.py` | Observation -> tensors, dataset cache builder |
| `seventeenlands/` | 17lands download, audit, split, turn replay, replay batching |
| `play/` | Claude player, random bot, ONNX policy player, eval runner and report |
| `experiments/` | Write-ups with configs and raw results (policy eval, coverage soak, engine smoke tests) |
| `engine/playmat/` | Patches for a browser client to play against the agents |
| `docs/decisions.md` | Dated design decisions and their reasons |

## Setup

Python 3.12, managed with [uv](https://docs.astral.sh/uv/). Engine runs need Java 21 and the XMage 1.4.62 release
(build steps in [engine/xmage/README.md](engine/xmage/README.md)).

```bash
uv sync           # create .venv from the lockfile
uv run pytest     # tests
```

Datasets, caches and checkpoints are kept out of Git. Every run records its config, dataset version, seed and commit.

## Credits

- Game data: [17lands public datasets](https://www.17lands.com/public_datasets), licensed CC BY 4.0. Deck lists
  under `engine/xmage/decks/17lands*` and the card statistics under `play/primer/` are derived from it.
- Rules engine: [XMage](https://github.com/magefree/mage) (MIT). A few XMage source files are patched onto our
  classpath and keep their original license headers.
- Not affiliated with or endorsed by Wizards of the Coast. Magic: The Gathering and card names are trademarks of
  Wizards of the Coast.
