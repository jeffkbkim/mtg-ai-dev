"""Decision tables from 17lands replays of one set (DSK by default, MTG_SET=FDN for Foundations), for the decisions a replay records exactly.

    uv run --group data python seventeenlands/decisions.py [--limit N]

Writes three Parquet tables to ~/mtg-data/17lands/<SET>/decisions/ (outside Git), one row per decision, each carrying
the game's split from splits.parquet (by draft, see prepare.py):

  mulligans.parquet   one row per hand seen: keep or mulligan, and for a kept hand after mulligans, the cards put
                      on the bottom (candidate hand minus opening hand)
  land_drops.parquet  one row per own turn with a land in hand: which land was played, or none
  attacks.parquet     one row per own turn with a creature on the battlefield at the start of the turn or an attack:
                      which creatures attacked

This is data preparation, not model input: cards are names, nothing is encoded. Labels are what the replay records.
Context that the replay doesn't record exactly is flagged, never filled in:
  - hand_start (land drops) is the hand recorded at the end of the previous turn plus this turn's draws. Moves 17lands
    doesn't record (flash permanents cast on the opponent's turn, cards returned to hand) can make it wrong;
    land_in_hand_start says whether every land played was in it.
  - attackers_available (attacks) is the creatures you had at the end of the previous turn. It misses creatures with
    haste cast this turn and includes creatures that died or were tapped before combat; attackers_in_available says
    whether every attacker was in it.
Games with a card outside our 276-card DSK list (Special Guests) are kept and flagged with has_special_guest.
"""
import argparse, json, os
from pathlib import Path

import polars as pl

SET = os.environ.get("MTG_SET", "DSK").upper()
DATA = Path.home() / f"mtg-data/17lands/{SET}"
REPO = Path(__file__).resolve().parent.parent
KEY = ["draft_id", "build_index", "match_number", "game_number"]
MAX_TURN = 30
BATCH = 50_000


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=None); a = ap.parse_args()
    cards = pl.read_csv(DATA.parent / "cards.csv")
    raw = dict(zip(cards["id"], cards["name"]))
    full = {h: n for n in raw.values() if " // " in n for h in n.split(" // ")}
    name = {i: full.get(n, n) for i, n in raw.items()}   # a split card / Room's halves count as the whole card
    is_land = {n: "Land" in (t or "") for n, t in zip(cards["name"], cards["types"])}
    is_land.update({full[h]: is_land.get(full[h], False) or is_land.get(h, False) for h in full})
    dsk = {c["name"] for c in json.loads((REPO / f"engine/vocab/{SET.lower()}_card_text.json").read_text())}

    def names(v):
        return [] if v in (None, "") else [name.get(int(x), x) for x in str(v).split("|") if x]

    lf = pl.scan_parquet(DATA / "parquet/replay_data.parquet")
    deck_cols = [c for c in lf.collect_schema().names() if c.startswith("deck_")]
    splits = pl.read_parquet(DATA / "splits.parquet")
    n = lf.select(pl.len()).collect().item() if a.limit is None else a.limit
    out = DATA / "decisions"; out.mkdir(exist_ok=True)
    tables = {"mulligans": [], "land_drops": [], "attacks": []}
    for start in range(0, n, BATCH):
        df = lf.slice(start, min(BATCH, n - start)).collect()
        rows = {k: [] for k in tables}
        for g in df.iter_rows(named=True):
            key = {k: g[k] for k in KEY}
            deck = [c[5:] for c in deck_cols if g[c]]
            game = {**key, "on_play": g["on_play"], "won": g["won"], "rank": g["rank"], "num_turns": g["num_turns"],
                    "num_mulligans": g["num_mulligans"], "has_special_guest": any(c not in dsk for c in deck)}
            # mulligans
            hands = [names(g[f"candidate_hand_{i}"]) for i in range(1, 8) if g[f"candidate_hand_{i}"]]
            opening = names(g["opening_hand"])
            for i, h in enumerate(hands):
                keep = i == len(hands) - 1
                bottomed = []
                if keep:
                    rest = list(opening)
                    for c in h:
                        if c in rest: rest.remove(c)
                        else: bottomed.append(c)
                rows["mulligans"].append({**game, "mulligan_index": i, "hand": h, "decision": "keep" if keep else "mulligan",
                                          "bottomed": bottomed, "bottomed_consistent": len(h) - len(bottomed) == len(opening) if keep else None})
            # own turns, in play order
            order = [(s, t) for t in range(1, MAX_TURN + 1) for s in (("user", "oppo") if g["on_play"] else ("oppo", "user"))]
            prev_hand, prev = opening, None   # prev: the turn before this one, for end-of-turn board state
            for side, t in order:
                if t > (g["num_turns"] or 0):
                    break
                p = f"{side}_turn_{t}_"
                if side == "user":
                    q = (lambda c: g[prev + c]) if prev else (lambda c: None)
                    ctx = {**game, "turn": t,
                           "user_life": q("eot_user_life"), "oppo_life": q("eot_oppo_life"), "oppo_hand_size": q("eot_oppo_cards_in_hand"),
                           "user_lands": names(q("eot_user_lands_in_play")), "oppo_lands": names(q("eot_oppo_lands_in_play")),
                           "user_creatures": names(q("eot_user_creatures_in_play")), "oppo_creatures": names(q("eot_oppo_creatures_in_play")),
                           "user_noncreatures": names(q("eot_user_non_creatures_in_play")), "oppo_noncreatures": names(q("eot_oppo_non_creatures_in_play"))}
                    hand = prev_hand + names(g[p + "cards_drawn"]) + names(g[p + "cards_tutored"])
                    lands_in_hand = [c for c in hand if is_land.get(c, False)]
                    played = names(g[p + "lands_played"])
                    if lands_in_hand or played:
                        rows["land_drops"].append({**ctx, "hand_start": hand, "lands_in_hand": lands_in_hand, "land_played": played,
                                                   "land_in_hand_start": all(hand.count(c) >= played.count(c) for c in played)})
                    attackers = names(g[p + "creatures_attacked"])
                    available = ctx["user_creatures"]
                    if available or attackers:
                        rows["attacks"].append({**ctx, "attackers_available": available, "creatures_cast_this_turn": names(g[p + "creatures_cast"]),
                                                "attackers": attackers, "blocked": names(g[p + "creatures_blocked"]),
                                                "attackers_in_available": all(available.count(c) >= attackers.count(c) for c in attackers)})
                prev_hand, prev = names(g[p + "eot_user_cards_in_hand"]), p
        for k, r in rows.items():
            if r:
                tables[k].append(pl.DataFrame(r, infer_schema_length=None).join(splits, on="draft_id", how="left"))
        print(f"{min(start + BATCH, n)}/{n} games", flush=True)
    summary = {}
    for k, parts in tables.items():
        t = pl.concat(parts, how="diagonal_relaxed")
        t.write_parquet(out / f"{k}.parquet", compression="zstd")
        summary[k] = {"rows": t.height, "by_split": dict(t.group_by("split").len().iter_rows()), "missing_split": t["split"].null_count()}
    summary["mulligans"]["kept_bottomed_consistent"] = float(pl.read_parquet(out / "mulligans.parquet").filter(pl.col("decision") == "keep")["bottomed_consistent"].mean())
    summary["land_drops"]["land_in_hand_start"] = float(pl.read_parquet(out / "land_drops.parquet")["land_in_hand_start"].mean())
    summary["attacks"]["attackers_in_available"] = float(pl.read_parquet(out / "attacks.parquet")["attackers_in_available"].mean())
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
