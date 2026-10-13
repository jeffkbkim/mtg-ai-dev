# Decisions

## DSK is the first target

The user wants to replay Duskmourn Limited and may add other historical draft formats later. We do not need to target all Magic cards. Generalization initially means unseen decks and positions within DSK, rather than unseen sets.

Use the actual chosen Arena draft pool plus basic lands and generated tokens/objects; do not assume every DSK-branded product card belongs to the draft pool. Confirm the pool from source data.

DSK has Rooms and hidden face-down cards. Preserve locked/unlocked door states, legal choices, and seat-specific knowledge. Check replay reconstruction and engine support before committing to a data pipeline.

## Learn the model; borrow infrastructure

Reuse rules, legal-action generation and suitable data reconstruction tools. The user owns model design and training implementation. MageZero and DraftZero are references rather than a requirement to adopt their architecture.

## No search in the first player

The first player scores legal choices directly. A value head may aid training without decision-time search. Search-generated training targets remain a possible later experiment.

## Architecture remains experimental

Compare simple shared card/entity encoding with attention and explicit graph relationships. Omit arbitrary positional encodings for unordered zones. Encode meaningful ordering for the stack/history and explicit ownership, zone and attachment relationships.

### Interaction layer (2026-10-09)

The interaction layer must accept any number of visible cards, ignore their order, and output one row per card so legal actions can point at card rows. Two families meet this and remain viable: attention (transformer blocks) and relation-style pairwise models (relation networks, or GNN message passing on explicit edges). DLRM-style flattened pairwise interaction, FM/DCN, RNN and CNN were ruled out for unordered zones. The user will build transformer blocks first, adapted from their LLM project, with a pooling (DeepSets) baseline to test whether interaction helps at all, and a relation network as the second contender to test which interaction works better. This is a hypothesis to test, not a settled winner.

### Decisions are sequential steps (2026-10-10)

A compound action is chosen as a sequence of single choices (for example: which spell or ability, then its target), each scored with its own softmax over the engine's legal options for that step. Actions point at card rows by index with explicit roles (source versus target). The engine integration must expose decisions at this granularity; whether XMage's player callbacks already do needs to be verified in its source.

### v1 model shape (2026-10-11)

- Input: each visible card's embedding is concatenated with its instance features and projected to D; global state is projected to D and appended as one extra entry (N+1 entries).
- Encoder: start with one transformer block (single-head self-attention, then FFN, both residual) over cards plus global state; measure deeper stacks and more heads later.
- Relations: engine-supplied directed edges `(edge_type, from_card, to_card)` add a learned scalar per edge type to the attention score of that pair. Both directions are separate types (for example blocks / blocked by). Upgrades to per-head and vector edge embeddings are later experiments.
- Stack order: "resolves before" / "resolves after" edges between every pair of stack entries; no stack-position feature.
- Decision context: the step type and whose decision it is go in the global state; a per-card flag marks the spell or ability currently being cast.
- Abilities: abilities on the stack are their own entries with an ability embedding from a stable ability vocabulary built by the engine adapter (XMage runtime ability IDs are per-game). Unmapped abilities must be reported, never replaced.
- Actions: fixed slots `[source | target | global | action type]`, giving `(A, 3D + D_a)` per decision. Source and target are gathered from the encoder outputs by index; the global slot is the global state's encoder output for every action, so PASS-style actions see the situation; empty source/target slots are zeros. At a target step the source slot holds the spell or ability being cast. ACTIVATE puts the card in the source slot and the ability embedding in the target slot. Embeddings use width D throughout for v1. An MLP scores each action; softmax over legal actions; cross-entropy against the chosen action. Multi-target spells are separate sequential target steps.

## Engine integration: XMage release jars plus our own classes (2026-10-13)

The user chose to build on the unmodified XMage 1.4.62 release jars with our own Java classes (`engine/xmage/`), rather than forking XMage or using the Playmat websocket client. A Java seat hands every real decision to Python as JSON lines with an observation built from XMage's per-seat view; every message is checked against full game state for hidden-information leaks. Fork XMage source only if a DSK card bug blocks us. Coverage is tracked per card through rejected moves and unmapped abilities reported in the run log. Write-ups: `/mnt/project-files/notes/xmage-step1-readiness.md` to `xmage-step4-encoder.md` (project files, not in Git).

## Research references

- [DSK runtime tests and Witchcraft contribution scope — 2026-10-07](../experiments/engine_smoke/README.md). Current XMage passes a limited gameplay smoke test, but the packaged MageZero route is not DSK-ready. Consider current XMage as a reference while evaluating focused Witchcraft contributions; no final switch or contribution implementation is decided.

- [Engine comparison, measured LOC and failing boundary probes — 2026-10-07](research/engine-comparison-2026-10-07.md). XMage remains tentative; the audit recommends testing its existing Python integration route first. No engine has passed this project's full DSK acceptance checks.

- DSK guide: https://magic.wizards.com/en/news/feature/duskmourn-house-of-horror-prerelease-and-draft-guide
- Public datasets: https://www.17lands.com/public_datasets
- XMage: https://github.com/magefree/mage
- MageZero: https://github.com/WillWroble/MageZero
- DraftZero: https://github.com/danieljbrooks/draft-zero
- Graph experiments: https://github.com/danieljbrooks/draft-zero/blob/main/docs/024-gnn-local-layers-and-games.md
