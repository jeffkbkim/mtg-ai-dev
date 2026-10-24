# Strong real drafted DSK decks from 17lands

Built from 17lands' public `game_data_public.DSK.PremierDraft.csv.gz` by

    python3 play/good_deck_pool.py ~/mtg-data/17lands/DSK/game_data_public.DSK.PremierDraft.csv.gz \
        engine/vocab/dsk_numbers.tsv ~/mtg-data/17lands/cards.csv engine/xmage/decks/17lands-good \
        --compare engine/xmage/decks/17lands/manifest.json engine/xmage/decks/17lands-r2/manifest.json

- Candidates: trophy drafts (7 wins, at most 2 losses) whose drafter's `user_game_win_rate_bucket` is at least 0.60.
  Same eligibility as `../17lands`: the draft's most-played build, 40 cards, every card in XMage's DSK set, nothing
  substituted. 19,243 trophy decks were eligible (1,374 skipped for not being 40 cards, 365 for cards XMage's DSK set
  lacks); 7,300 of them at drafter bucket >= 0.60.
- Deck score: mean GIH WR of the deck's nonland cards, weighted by copies. GIH WR is computed from all ~1M game rows
  (a card is in hand if it was in the opening hand or drawn); it is in `gih_wr.json`.
- `good_NN.dck`: the top 70 by deck score, 00 best. The NAME line gives record, rank, drafter bucket, deck score and
  main colors (splash colors are in the manifest). No overlap by draft id with `../17lands` or `../17lands-r2`.
- `manifest.json`: thresholds, counts, skip reasons, and per deck the draft id, record, rank, drafter bucket, score and cards.

17lands data is CC BY 4.0 (17lands.com).
