# Real drafted DSK decks from 17lands, second pool

Built like `../17lands` (see its README) by `play/deck_pool.py ... --n 80 --seed 8 --exclude ../17lands/manifest.json`:
80 `typical_NN.dck` (drafts with at least 3 games, sampled uniformly) and 80 `trophy_NN.dck` (7 wins, at most 2
losses), none of them drafts from the first pool. Same eligibility rules: 40-card decks with every card in XMage's DSK
set, nothing substituted. `manifest.json` has the draft ids, records, colors and card counts.

Used for the plan-vs-no-plan pairs (`claude-games/plan-pairs/`), paired 00/01, 02/03, ... within each kind.

17lands data is CC BY 4.0 (17lands.com).
