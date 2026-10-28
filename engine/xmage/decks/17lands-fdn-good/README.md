# FDN good deck pool (17lands Foundations Premier Draft)

Built 2026-10-28 by `MTG_SET=FDN python3 play/good_deck_pool_v2.py --tier2-cap 4` with the DSK v2 pool's rules:
most-played 40-card build per draft, drafter played >= 100 games and long-run win-rate bucket >= 0.66, Jeff's colour rule
(two main colours, at most a light splash), build checks (15-18 lands, >= 13 bodies, >= 4 two-drops, top end), 15
shortlisted per pair by drafter bucket, reviewed by Claude Opus 5.5 medium (`review_decks.py`, FDN wording; $7.65 for
150 decks), kept rating >= 3, up to 10 per pair. ★★ = review 4/5 and no build red flag, at most 4 per pair (Jeff's cap,
2026-10-26; the extra ones are ★ with `tier_capped`). Colour-pair win rates for the stats come from the game data
(`play/color_ratings_17lands.py`), not 17lands' ratings page.

98 decks: 23 ★★ (WB, BR, WG, RG 4 each; WR, UG, BG 2; WU 1; UB, UR 0), 75 ★. UB has 8 decks (7 of its 15 shortlisted
were rated 2/5). `manifest.json` has every deck's review, stats and mana score.
