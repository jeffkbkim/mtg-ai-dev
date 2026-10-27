# Exporting our games to the DraftZero self-play format: field mapping and gaps

2026-10-27. Target: [danbrooks/draftzero-selfplay-games](https://huggingface.co/datasets/danbrooks/draftzero-selfplay-games),
checked today (repo sha `b10e310`).

## What the target is

- **No games yet.** The repo holds only a README and `.gitattributes`. The card says "empty for now" and that the
  layout "may still change before the first upload".
- **The card predates DraftZero v0.2.0.** It was written 2026-10-05. On 2026-10-17 DraftZero went gorge-only, and the
  action vocabulary the card points to (`assets/vocab/FDN_SPG.tsv`) is no longer in the repo (404).
- **It is a training-tensor format, not a text replay.** Positions are MageZero feature hashes and options are indices
  into an FDN action vocabulary. This is different from what Will asked for on 2026-10-26 (a 17lands/Untapped-style
  text replay their converters can read).

## Their layout

One gzipped JSON line per seat per game: `pair`, `swap`, `seat`, `bot`, `result`, `records[]`.
Each record: `features`, `type`, `turn`, `legal`, `visits`, `q`, `heuristic`.

## Field mapping

| Their field | Ours | Status |
|---|---|---|
| `pair` | game id / batch index | have (we use game ids, not deck-pair indices) |
| `swap` | none | gap: our games are not played as seat-swapped pairs; would be `null` |
| `seat` | `seat` (A/B) | have |
| `bot` | `player` / config seat (`claude:claude-opus-5-5:high:...`, `human:kimster`, `xmage_ai`) | have |
| `result` | `games.jsonl` winner, draw | have |
| `turn` | `obs.entries[global].turn` | have |
| `type` | `kind` | partial, see below |
| `features` | `obs` (our own entries + edges) | **gap**: their hashes come from MageZero's Java encoder on the live XMage game |
| `legal` | `options` (action, source card, target) | **gap**: indices into an FDN vocab that doesn't cover DSK and no longer exists |
| `visits` | `choice` | partial: we have no search, so one-hot on the chosen option |
| `q` | none | gap: no search value; `null` |
| `heuristic` | none | gap: MageZero's evaluator never ran; `null` |

### Decision types

Theirs: `PRIORITY`, `CHOOSE_USE`, `CHOOSE_TARGET`. Ours (Playmat counts so far):

| Ours | Count | Maps to |
|---|---|---|
| PRIORITY | 6,632 | PRIORITY |
| ATTACK | 1,376 | none directly. We record the whole attack as one choice; MageZero asks "attack with X?" once per creature. Splitting is possible but the per-creature order is inferred |
| TARGET | 527 | CHOOSE_TARGET |
| BLOCK | 406 | CHOOSE_TARGET (their card: "which attacker to block") |
| USE | 329 | CHOOSE_USE (includes mulligans) |
| CHOOSE, CHOOSE_CARDS, TRIGGER_ORDER, TARGET_CARDS, MODE, CHOICE | 749 | no equivalent |

## What their format would drop from ours

- Claude's reasoning text, the prompt, readable option labels, decision time.
- Decision kinds outside their three (about 7% of Playmat decisions).
- Whether a decision was auto-passed, a rule, or a real choice (`source`: claude / human_ui / rule / xmage_ai).
- Decklists, engine and code versions, leak-check results.

## Sources

- Playmat (`~/mtg-data/playmat-games/`): 90 games so far, 87 Claude vs Jeff (human), 3 involving XMage's AI.
- Claude vs Claude (project files `claude-games/`): 161 clean, 198 suspect per the manifest.

Both come from the same recorder (`seat-A.jsonl`, `seat-B.jsonl`, `games.jsonl`, decks, config). The full decision log
stays the source of truth; any export is derived from it.

## Built: `play/export_replays.py` (2026-10-27)

Jeff chose to provide two versions. Both are derived from the decision logs, read through `play/manifest.py`
manifests (clean games only by default):

- `draftzero-style.jsonl.gz`: the layout above, one line per seat per game. `features`, `q`, `heuristic` are null;
  `legal` is readable option text (plus `legal_actions` with source and target card names); `visits` is one-hot on
  the option played. Each record keeps our `kind`, `step`, the seat's observation, who decided (Claude, human UI,
  rule) and Claude's reason. All decision kinds are kept; ours that have no DraftZero type keep our name.
- `17lands-style.csv.gz`: one row per seat per game with 17lands `replay_data` column names and Arena ids from
  17lands `cards.csv` (DSK, tokens from TDSK). Exact: mulligans, candidate and opening hands, each turn's lands,
  spells cast (split creature / other / instant-sorcery), attackers, blockers and what they blocked, the deck.
  Approximate: `cards_drawn` (anything that entered the hand between two of the seat's decisions) and the `eot_*`
  columns (the state at the first decision of a later turn, since we only see the game when someone has a choice).
  Left out: mana spent, combat damage, creatures killed, discards, tutors, ability ids (we write the ability's source
  card to `x_user_ability_sources` / `x_oppo_ability_sources` instead). Face-down cards are left out of board lists.
- Games are skipped, and listed in `export-manifest.jsonl`, when a human player isn't passed with `--human`, a deck
  has non-DSK cards, or a deck file is missing.

First run on Playmat (76 clean games, `--human kimster`): 37 games, 5,117 decisions exported; 38 skipped for other
human names (binpy 24, ffffxxxx 8, testercla 3, Smoketest 2, prpb14qp 1) and 1 for a missing deck. A spot check of
one game against XMage's game log matched every land, spell, attack and draw.
