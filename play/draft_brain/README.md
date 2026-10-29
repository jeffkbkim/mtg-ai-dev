# Draft brains

The bot seats in a Playmat draft ask this service which card to pick and which deck to build. Each seat can have a
different brain, chosen when the draft is hosted.

```
uv run --group brain python -m play.draft_brain.server        # 127.0.0.1:17190; engine/playmat/run.sh starts it
```

| brain | what it is | weights |
|---|---|---|
| `statdraft` (default) | [statistical-drafting](https://github.com/danieljbrooks/statistical-drafting) (MIT): a per-set MLP trained on 17lands Premier Draft picks; sees the pool only | `~/mtg-data/draft-brains/statdraft/{DSK,FDN}_Premier.onnx` + card lists |
| `draftfm` | [DraftFM](https://github.com/brianward92/mtga) (Apache-2.0): one model over card features for any set; sees the pool and the pack/pick number | `~/mtg-data/draft-brains/draftfm/` |
| `gih` | our 17lands train split: games-in-hand win rate, then a bonus for the pool's two main colours from pick 6 | `~/mtg-data/17lands/ratings/{dsk,fdn}_card_gih.json` (`seventeenlands/card_ratings.py`) |
| `xmage` | XMage's own bot ratings (the server keeps its built-in pick) | none |

All three learned brains were trained on (or computed from) public 17lands drafts. Their agreement with human picks in
our validation/test drafts is not a fair score for them, since those drafts come from the same dumps; judge them by
games played with their decks.

## Adding a brain (your own pick model)

A brain is a class in `brains.py` with a `name`, a `label`, the `sets` it knows and one method:

```python
def scores(self, set_code, pack, pool, pack_number, pick_number) -> list[float | None]:
    """One score per card in `pack` (higher = pick it); None for a card you don't know."""
```

- `pack`: the card names in the booster now, as XMage names them (a Room is `"Left // Right"`).
- `pool`: the names this seat picked so far, in pick order.
- `pack_number`, `pick_number`: count from 0 (pack 1 pick 1 is 0, 0).

Add it to `BRAINS`; it shows in the host dialog's brain list after the service restarts. Load weights in `__init__`
from outside Git. A brain that fails to load is left out and the others still serve.

Deck building (`deckbuild.py`) is shared by every brain for now: the best two colours by 17lands win rate, 23 spells
(at least 14 creatures when there are, at most 4 of mana value 6+) and 17 basics split by coloured pips.
