"""Per-card ratings from our 17lands data of one set (DSK by default, MTG_SET=FDN for Foundations), for the draft bots.

    uv run --group data python seventeenlands/card_ratings.py

Writes ~/mtg-data/17lands/ratings/<set>_card_gih.json: for each card, games in hand (opening hand or drawn), the win
rate of those games (GIH WR, the usual 17lands card-quality number), and the average pick it was taken at (ATA). Only
the train split is used, so validation and test drafts stay unseen by anything built on these numbers.
"""
import json, os
from pathlib import Path

import polars as pl

SET = os.environ.get("MTG_SET", "DSK").upper()
DATA = Path.home() / f"mtg-data/17lands/{SET}"
OUT = Path.home() / f"mtg-data/17lands/ratings/{SET.lower()}_card_gih.json"


def main():
    train = pl.scan_parquet(DATA / "splits.parquet").filter(pl.col("split") == "train").select("draft_id")
    games = pl.scan_parquet(DATA / "parquet/game_data.parquet").join(train, on="draft_id", how="semi")
    cols = games.collect_schema().names()
    names = [c[len("drawn_"):] for c in cols if c.startswith("drawn_")]
    in_hand = [((pl.col(f"drawn_{n}") + pl.col(f"opening_hand_{n}")) > 0).alias(n) for n in names]
    hand = games.select([pl.col("won").cast(pl.Int64)] + in_hand)
    agg = hand.select([pl.col(n).sum().alias(f"g|{n}") for n in names] + [(pl.col(n) * pl.col("won")).sum().alias(f"w|{n}") for n in names]).collect(engine="streaming")
    row = agg.row(0, named=True)

    picks = pl.scan_parquet(DATA / "parquet/draft_data.parquet").join(train, on="draft_id", how="semi")
    ata = (picks.group_by("pick").agg(pl.col("pick_number").mean().alias("ata"), pl.len().alias("taken"))
           .collect(engine="streaming"))
    ata = {r["pick"]: (r["ata"] + 1, r["taken"]) for r in ata.iter_rows(named=True)}   # 17lands pick_number counts from 0

    out = {}
    for n in names:
        g, w = row[f"g|{n}"], row[f"w|{n}"]
        a = ata.get(n, (None, 0))
        out[n] = {"gih_games": int(g), "gih_wr": (w / g) if g else None, "ata": a[0], "taken": int(a[1])}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=0))
    rated = sorted((v["gih_wr"], k) for k, v in out.items() if v["gih_wr"] and v["gih_games"] >= 500)
    print(f"{len(out)} cards, {len(rated)} with 500+ games in hand; best {rated[-3:]}; worst {rated[:2]} -> {OUT}")


if __name__ == "__main__":
    main()
