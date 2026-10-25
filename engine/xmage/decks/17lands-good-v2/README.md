# Good DSK decks chosen by build quality (v2): the starred pool since 2026-10-25

Replaced `../17lands-good` as Playmat's starred (★/★★) pool on 2026-10-25 (Jeff's yes): engine/playmat/dsk_starters.py
lists these as dsk-good-v2-NN.dck, named "v2_NN"; the first pool's decks are no longer listed but stay rated in
strengths.json. Built by

    python3 play/good_deck_pool_v2.py --parse-cache <scratch>/parsed.json.gz

(defaults: `--data ~/mtg-data/17lands/DSK/game_data_public.DSK.PremierDraft.csv.gz --thresholds 0.66 0.64 0.62 0.60
--min-user-games 100 --min-build-games 3 --min-creatures 13 --shortlist-per-pair 15 --per-pair 10 --keep-rating 3
--min-rating 4 --model claude-opus-5-5 --effort medium`). The parse cache is optional and stays outside Git.
Rerunning reuses `review_cache.json`, so it costs nothing unless the shortlist changes.

## How decks are chosen

1. **Eligible** (deck_pool.py's rule): the draft's most-played build, 40 cards, every card in
   `engine/vocab/dsk_numbers.tsv`, nothing substituted. 155,983 of 173,545 drafts.
2. **No win requirement.** Instead:
   - the build was played in at least 3 games (143,614);
   - the drafter's `user_n_games_bucket` is at least 100. Without this the top win-rate buckets (0.70+) are mostly
     drafters with 10-50 games, whose "long-run" win rate is noise (100,397 left);
   - Jeff's colour rule, `two_colors()` from `engine/playmat/dsk_starters.py` used as-is: exactly 2 main colours,
     at most one splash colour, in at most 3 nonland cards, with at least 3 lands that make it (80,353). Also every
     nonland card's coloured pips must be within main + splash (1,182 dropped);
   - build checks (stats from `play/review_decks.py`): 15-18 lands, at least 13 creatures (34,284 fail; no
     exceptions were made), at least 4 two-drops (859 fail), at most 3 cards at 6+ and at most 7 at 5+ (4,119 fail),
     lands (60 fail). 41,730 pass all.
   - drafter `user_game_win_rate_bucket` >= **0.66**: the highest of 0.66/0.64/0.62/0.60 at which every pair has at
     least 15 candidates. 659 candidates.

   | bucket >= | WU | UB | BR | RG | WG | WB | UR | BG | WR | UG |
   |---|---|---|---|---|---|---|---|---|---|---|
   | 0.66 | 85 | 20 | 63 | 129 | 37 | 33 | 15 | 40 | 192 | 45 |
   | 0.64 | 189 | 35 | 144 | 252 | 80 | 69 | 43 | 87 | 454 | 103 |
   | 0.62 | 498 | 93 | 354 | 568 | 202 | 125 | 92 | 225 | 961 | 232 |
   | 0.60 | 1030 | 157 | 683 | 1065 | 399 | 233 | 171 | 469 | 1706 | 460 |

3. **Shortlist**: per pair, the 15 candidates with the highest drafter bucket (ties: mana score, then a hash of the
   draft id). 150 decks.
4. **Review**: `play/review_decks.py`'s reviewer, same system prompt (sha `53639186c19e`) and same user prompt, so
   ratings compare directly with `../17lands-good/REVIEW.md`. The reviewer sees the list, card text and counts, not
   the record, rank or drafter. 149 new calls, 1 reused from `../17lands-good/review_cache.json`; **cost $2.85**.
5. **Keep** rating >= 3, up to 10 per pair. **Tier 2 (★★)** = rating >= 4 and no build red flag from
   `review_decks.red_flags` (3+ colours with < 3 fixers, < 5 two-drops, 5+ cards at 6+, lands outside 16-18).
   The weak-archetype flag (17lands pair win rate below 53%: UB, WG, WB, UR) is **not** used for the tier, because
   it judges the colour pair, not the build, and would bar four pairs from tier 2; it is kept per deck as
   `archetype_flag`. With it, tier 2 would be 17 decks instead of 27.
6. **Rank** (file number, 00 first): tier, then review rating, then mana score, then drafter bucket. Record and
   the GIH deck score are in the manifest as information only.

**Mana score** (10 best): for each main colour, sources = lands that can make it (basics, duals, Terramorphic Expanse,
Valgavoth's Lair); need = 7, or 8 if the colour appears in 8+ nonland cards or any card needs two of its pips, or 9
if a card of mana value <= 3 needs two of its pips; subtract the shortfall below need, 0.5 per splash card, and 1 more
if a splash card needs two splash pips or the splash has fewer than 4 sources. 90 of the 100 kept decks score 10,
so it rarely separates decks.

## Result: 100 decks, 27 tier 2, 73 tier 1

| pair | kept | tier 2 | tier 1 | reviewed | rated 4 | rated 3 | rated <= 2 (dropped) | weak-archetype flag |
|---|---|---|---|---|---|---|---|---|
| WU | 10 | 4 | 6 | 15 | 4 | 11 | 0 | no |
| UB | 10 | 3 | 7 | 15 | 3 | 11 | 1 | yes |
| BR | 10 | 5 | 5 | 15 | 5 | 10 | 0 | no |
| RG | 10 | 0 | 10 | 15 | 0 | 15 | 0 | no |
| WG | 10 | 4 | 6 | 15 | 4 | 8 | 3 | yes |
| WB | 10 | 1 | 9 | 15 | 1 | 13 | 1 | yes |
| UR | 10 | 2 | 8 | 15 | 2 | 11 | 2 | yes |
| BG | 10 | 5 | 5 | 15 | 5 | 10 | 0 | no |
| WR | 10 | 3 | 7 | 15 | 3 | 11 | 1 | no |
| UG | 10 | 0 | 10 | 15 | 0 | 14 | 1 | no |

Every pair reached 10. No deck was rated 5. RG and UG have no tier-2 deck: none of their 15 shortlisted decks was
rated 4. Only 2 of the 100 decks splash. Drafter buckets: 0.66-0.74 (51 at 0.70); drafter games bucket 100 (95) or
500 (5). Records vary (42 decks reached 7 wins; some went 2-3), since record is not used.

Each `.dck` NAME line is the name Playmat could use later, e.g. `★★ good_00 · WR aggro (red-heavy) · review 4/5`
(colours, then the reviewer's archetype with its own colour prefix removed). Nothing is wired into Playmat.

`manifest.json`: thresholds, funnel counts, candidates per threshold and pair, shortlist ratings, reviewer and cost,
overlap, and per deck: file, pool rank, Playmat name, tier, draft id, build index and games, record, colours, splash,
drafter win-rate and games buckets, 17lands rank (`rank_17lands`), review, mana score with sources/need per colour,
stats and red flags, archetype flag, GIH deck score (info), `in_current_pool`, and the cards.

## Differences from `../17lands-good`

- Current: 7-win trophies (<= 2 losses) by drafters at bucket >= 0.60, ranked by mean GIH WR; 70 decks, 4- and
  5-colour piles included. Only 58 of its 70 pass the colour rule, and those cover just WU, WR, UG and RG (WU 27,
  WR 19). This proposal: any record, bucket >= 0.66 with 100+ games, colour rule and build checks before review,
  ranked by review, 10 decks for each of the 10 pairs.
- Overlap by draft id: 1 deck (`031392d73d024fe882fb5c904c96b576`, here `good_07`, there `good_69`, tier 2 in both).
- The current pool's REVIEW.md rated its 70 decks 2: 13, 3: 42, 4: 15; this shortlist of 150: 2: 9, 3: 114, 4: 27.

## Known limits

- One review per deck from one model; ratings 3 and 4 are coarse and not proof of playing strength. Games against
  fixed opponents are the real test.
- `two_colors()` counts a splash source only for basics, lands naming the colour, "any color" or basic-land
  fetching; Valgavoth's Lair ("chosen color") is not counted there, though the mana score counts it.
- `user_game_win_rate_bucket` is 17lands' bucket of the drafter's overall win rate, not their win rate with this
  deck, and the 17lands rank of these drafts ranges from bronze to mythic.

17lands data is CC BY 4.0 (17lands.com).

## 2026-10-25 top-up and re-review

- Body count: `play/review_decks.py` now counts token makers, manifest dread (Rooms too) and creature recursion as
  bodies beside creature cards; `good_deck_pool_v2.py`'s creature check uses it, and the reviewer is told the count.
- WB top-up: `good_deck_pool_v2.py --pairs WB --thresholds 0.66 --shortlist-per-pair 40 --per-pair 40 --keep-rating 4
  --exclude 17lands-good-v2/manifest.json --out ../17lands-good-v2-wb` reviewed 40 WB decks (2 rated 2, 30 rated 3,
  8 rated 4; $0.78). The 8 rated 4 are added here as good_100..good_107 (7 ★★; good_107 stays ★ for its 15 lands).
- Re-review of the decks whose review mentioned manifest (`play/rereview_bodies.py`): 18 here, 39 in ../17lands-r2.
  Here only good_96 (UG eerie/manifest) changed, 3 -> 2, so it loses its star (file dsk-goodx-v2-96). The old review is
  kept as `review_before`.
