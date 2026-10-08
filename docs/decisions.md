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

## Research references

- [DSK runtime tests and Witchcraft contribution scope — 2026-10-07](../experiments/engine_smoke/README.md). Current XMage passes a limited gameplay smoke test, but the packaged MageZero route is not DSK-ready. Consider current XMage as a reference while evaluating focused Witchcraft contributions; no final switch or contribution implementation is decided.

- [Engine comparison, measured LOC and failing boundary probes — 2026-10-07](research/engine-comparison-2026-10-07.md). XMage remains tentative; the audit recommends testing its existing Python integration route first. No engine has passed this project's full DSK acceptance checks.

- DSK guide: https://magic.wizards.com/en/news/feature/duskmourn-house-of-horror-prerelease-and-draft-guide
- Public datasets: https://www.17lands.com/public_datasets
- XMage: https://github.com/magefree/mage
- MageZero: https://github.com/WillWroble/MageZero
- DraftZero: https://github.com/danieljbrooks/draft-zero
- Graph experiments: https://github.com/danieljbrooks/draft-zero/blob/main/docs/024-gnn-local-layers-and-games.md
