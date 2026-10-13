# Plan

## Current milestone: validate the DSK development path

1. Connect the local scaffold to a GitHub repository and clone it onto the Mac.
2. Audit DSK public data availability and replay fidelity before a bulk download.
3. Check candidate engine/integration coverage for DSK, especially Rooms, manifest dread, impending, triggers and hidden information.
4. Run two fixed DSK 40-card decks through a minimal observation/legal-action interface.
5. Prepare a small, documented dataset and a meaningful evaluation baseline.

## Following milestones

- User implements a small card/state encoder and legal-action scorer.
- Train from random weights on a small imitation dataset; inspect mistakes.
- Evaluate direct-policy gameplay against fixed baselines.
- Expand deck diversity within DSK and test on held-out draft decks.
- Compare MLP/shared-entity, attention and graph architectures under comparable budgets.
- Add reinforcement learning and an opponent pool when the environment is reliable.
- Experiment with search separately; add drafting/deckbuilding after gameplay works.

## Status

Private GitHub repository created and scaffold is available locally. The [engine comparison](research/engine-comparison-2026-10-07.md) now has a [DSK runtime follow-up](../experiments/engine_smoke/README.md): current XMage completed four games with exact synthetic DSK decks, while the older MageZero bundle failed card coverage. Witchcraft's DSK parser/bridge was audited and a contribution sequence proposed. Python-controlled policy decisions, hidden-information validation, complete DSK coverage, data audit and training remain pending. No engine selection is final.

Update 2026-10-13: XMage is now driven from Python through our own seat class on the release jars (`engine/xmage/`): decisions with per-seat observations, leak checks (0 leaks over 50+ recorded games, planted leaks caught), and an encoder (`engine/encode.py`) that turns recorded decisions into batch tensors passing `validate_batch`. Only two synthetic smoke decks have been played so far; real drafted decks, wider card coverage and data audit remain pending.
