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

### Cards revealed from hand stay visible (2026-10-23)

Approved by the owner. XMage forgets a reveal at the next priority or update event, often before the seat's next
decision, so a card the opponent revealed from hand vanished from the observation while still in that hand. The
observer now remembers it (per game and seat) and keeps emitting it as zone `HAND`, `mine: false`, `revealed: true`
until the card changes zone (new zone change counter), the game ends or its turn is rolled back; a card revealed
from a library is not remembered, even if it then goes to a hand. The leak checks whitelist only those cards. The text renderer shows `opp HAND (revealed) <name>` and logs the reveal. Check:
`engine/xmage/RevealCheck.java`.

## Research references

- [DSK runtime tests and Witchcraft contribution scope — 2026-10-07](../experiments/engine_smoke/README.md). Current XMage passes a limited gameplay smoke test, but the packaged MageZero route is not DSK-ready. Consider current XMage as a reference while evaluating focused Witchcraft contributions; no final switch or contribution implementation is decided.

- [Engine comparison, measured LOC and failing boundary probes — 2026-10-07](research/engine-comparison-2026-10-07.md). XMage remains tentative; the audit recommends testing its existing Python integration route first. No engine has passed this project's full DSK acceptance checks.

- DSK guide: https://magic.wizards.com/en/news/feature/duskmourn-house-of-horror-prerelease-and-draft-guide
- Public datasets: https://www.17lands.com/public_datasets
- XMage: https://github.com/magefree/mage
- MageZero: https://github.com/WillWroble/MageZero
- DraftZero: https://github.com/danieljbrooks/draft-zero
- Graph experiments: https://github.com/danieljbrooks/draft-zero/blob/main/docs/024-gnn-local-layers-and-games.md

## 17lands DSK split (2026-10-22)

Train/validation/test is frozen by draft: `sha256("mtg-ai-dsk-split-v1:" + draft_id)[:8] % 100`, below 80 train, below 90 validation, else test (`seventeenlands/prepare.py split`, `~/mtg-data/17lands/DSK/splits.parquet` on the mini). Every pick, game and replay of a draft shares its split. Changing it means a new salt and version, not editing this one.

## Playing against our AI in a browser: Playmat (2026-10-23)

Jeff chose [Playmat](https://github.com/arcanite24/playmat) (an Arena-style web client on an XMage 1.4.62 fork) to play our
AI from a browser, after a Reddit and GitHub survey of XMage clients. It does not replace the engine integration above:
our training and evaluation runs stay on the release jars. Our changes live in `engine/playmat/` as a patch series
against one pinned Playmat commit plus our seat plugin, not in a fork. Playmat's server carries our two XMage rule fixes
so its games follow our rules. Every game there is recorded in PySeat's decision format; Jeff's decisions say how
exactly a browser answer maps to our options, and XMage AI decisions are flagged clairvoyant (not imitation labels).

## Playmat: Claude plays first by rule, a good-decks pool, Claude's model and effort per table (2026-10-23)

- The Claude seat no longer chooses play or draw: it always plays first (`PLAY_DRAW=rule`, recorded `"source": "rule"`),
  so no training row comes from that choice. `PLAY_DRAW=claude` restores the model's choice.
- `engine/xmage/decks/17lands-good`: 70 decks from 7-win drafts (at most 2 losses) whose drafter's win-rate bucket is
  at least 0.60, kept by deck score (mean GIH WR of nonland cards over all games). The Claude AI's random Playmat deck
  comes from this pool. The score measures card quality only, not curve or synergy.
- 2026-10-25: `engine/xmage/decks/17lands-good-v2` replaces it as the starred pool (Jeff's yes): 100 decks, 10 per
  colour pair, chosen by build checks and drafter skill instead of a win requirement, every deck review-rated 3 or 4
  (★★ = 4). The first pool is no longer listed (its files and ratings stay, so saved copies still get matched).
- 2026-10-25: decks count bodies, not just creature cards: creature cards plus token makers, manifest dread (Rooms too)
  and creature recursion (`review_decks.makes_bodies`), in the >= 13 build check and in what the reviewer is shown. No
  win/loss filter (Jeff: a 7-x record is noise). A WB top-up under this count added 8 decks rated 4/5 to v2
  (`17lands-good-v2-wb`, v2_100..107); the manifest-dread decks of v2 and r2 were re-reviewed (`play/rereview_bodies.py`).
- ★★ capped at 4 per colour pair (Jeff 2026-10-26): the extra ★★ decks (WB 4, BG 1, BR 1) are ★ now, rating unchanged
  (`tier_capped` in the manifest). A fill for the pairs short of 4 reviewed 105 more candidates ($1.80): 3 rated 4/5
  (RG 2, WR 1, added as v2_108..110); UG 0 of 30, UR 0 of 15 and UB 0 of 10 reached 4/5, so those stay short.
- Deck reviewer v2 prompt (2026-10-26, `experiments/reviewer_bias`): v1 under-rated UG (residual -0.34 against card
  quality and drafter skill) and manifest decks, mostly for "few creatures"; v2 counts manifest dread, tokens and
  recursion as bodies. Test set: UG/manifest +0.15, control +0.05. v2 is the default from now on (REVIEW_SYSTEM=v1 for
  the old cache keys); earlier pool ratings stay v1 except the UG decks, re-reviewed with v2 (`reviewer_system`). UG
  gets one ★★ (v2_111).
- The web client's AI settings choose the Claude model (Opus 5.5, Sonnet 5.5) and effort; both are recorded with each
  decision, and games with different settings must not be pooled as one player.
- Blocks XMage refused are recorded as `mapping: "refused"` (choice -1), not as decisions; the accepted blocks are
  recorded from what the engine holds.

## Playmat's Claude uses primer v2 (2026-10-24)

Primer v2 (no win rates; archetype plans, cards to respect, mandatory checks, principles from reviewed games) replaced
v1 for Playmat's Claude seat after a puzzle test on 19 frozen decisions (notes/puzzles-v1-vs-v2-2026-10-24.md): it fixed
3 of 9 known mistakes and broke none of 10 controls, Opus high, 3 samples each. Small sample; batch match.py runs stay
on v1 unless --primer v2. The prompt hash on every decision keeps the two apart.
