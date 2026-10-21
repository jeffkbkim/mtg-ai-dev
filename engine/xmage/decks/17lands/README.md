# Real drafted DSK decks from 17lands

Built by `play/deck_pool.py` from 17lands' public `game_data_public.DSK.PremierDraft.csv.gz` (seed 7), with collector
numbers from XMage's card database (`engine/vocab/dsk_numbers.tsv`, dumped by `engine/xmage/DskNumbers.java`).

- `typical_NN.dck`: 20 drafts sampled uniformly from drafts that played at least 3 games, so archetypes appear about as
  often as 17lands users draft them.
- `trophy_NN.dck`: 20 drafts that reached 7 wins with at most 2 losses.
- Each deck is the draft's most-played build. Only 40-card decks with every card in XMage's DSK set were eligible:
  of 173,545 drafts, 14,279 were skipped for not being 40 cards and 3,283 for Special Guests cards XMage's DSK set
  doesn't have (Unholy Heat, Phantasmal Image, Damnation, ...). Nothing was substituted.
- `manifest.json`: draft id, record, colors, rank, the 17lands user's win-rate bucket and the card counts per deck.

17lands data is CC BY 4.0 (17lands.com). Decks 00-09 of each kind are used for the plan retest; 10-19 are kept unused.
