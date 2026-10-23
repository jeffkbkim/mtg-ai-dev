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

Update 2026-10-19: a Claude player (`play/`) plays DSK through two Python-driven XMage seats and records every decision with reason, tokens and cost. First test: 5-0 against the random bot, one Claude-vs-Claude game played; about $0.7 (vs random) to $3.2 (Claude vs Claude) API-equivalent per game. Its strength against a real opponent is unmeasured.

Update 2026-10-20: reviews of the Claude games found and fixed empty opening hands (every earlier recorded game started with 0 cards), Aura ownership, a `pass_until` bug that could skip a seat's own turns, and run-stopping/hang risks; the runner now stops on any engine-flagged leak. A rare XMage layer-timestamp bug was confirmed and documented (`engine/xmage/README.md`). The Claude player can now get an optional, versioned lessons section (`play/primer/lessons_v1.md`) to be A/B tested against no lessons.

Update 2026-10-20: DSK card coverage soak on the Mac mini (`experiments/coverage_soak/`): 2,318 random-vs-AI games, every non-basic DSK card reached play at least once. Found a real hidden-information leak (opponent-paid discard costs, mainly Osseous Sticktwister, show the other player's hand), an XMage AI crash on some blocks, seat options XMage refuses, unkeyed abilities, and substring false positives in the leak checker. Details in [results-2026-10-20.md](../experiments/coverage_soak/results-2026-10-20.md).

Update 2026-10-22: 17lands DSK Premier Draft data downloaded on the Mac mini, audited and split by draft (`seventeenlands/README.md`): 1,011,949 games and replays, 7.08M picks, no duplicates; 10 Special Guests cards are in 2.1% of decks and not yet in our vocabulary. Replays record mulligans, land drops and attack sets exactly; spell order, timing and targets and block assignments would be inferred. A nightly soak re-runs the 2,400-game coverage soak on the mini when the seat code changes.

Update 2026-10-23: 17lands games replay in XMage turn by turn (`seventeenlands/turn_replay.py`, `engine/xmage/ReplaySeat.java`): on 300 random games, 88.9% of turns reproduce the recorded end of turn up to a game's first miss, 70.2% of all turns once misses are reset to the record. The unrecorded details (order, timing, targets, block pairing) are found by a per-turn search with XMage's rollback; those are inferred labels. Results and limits in `seventeenlands/TURN_REPLAY.md`.

Update 2026-10-23: Jeff can play DSK against our Claude player (or XMage's AI, or watch the two) in Playmat in a browser on the home network (`engine/playmat/`). Every game is recorded under `~/mtg-data/playmat-games/` in our decision format. Smoke test: Claude beat XMage's AI in 19 turns ($2.51, 14 min, 177 decisions, no leaks); review.py, summarize.py and encode.py read the recording unchanged.
