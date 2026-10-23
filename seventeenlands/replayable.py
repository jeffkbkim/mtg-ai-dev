"""What share of 17lands DSK games could be replayed move for move in XMage from the replay alone?

    uv run --group data python seventeenlands/replayable.py [--games 20000] [--seed 0]

A game counts as fully replayable only if nothing about either player's moves has to be guessed. Each test below
is one reason it might not be; a game must pass all of them:
  hand      the user's hand rebuilt from draws and plays matches 17lands' end-of-turn hand every turn
  order     no turn where one player made 2+ plays (spells or abilities), whose order isn't recorded
  timing    no turn where the active player both cast something and attacked (before or after combat isn't recorded)
  targets   no spell or ability whose text says "target" (targets aren't recorded)
  blocks    no combat where 2+ attackers met any blockers (which blocker took which attacker isn't recorded)
  guests    no Special Guest in the user's deck (not in our 276-card list yet)
The opponent's unrevealed cards are unknown in every game; they never affect what was played, so they don't count here.
Writes replayable.json next to the data.
"""
import argparse, collections, json, random
from pathlib import Path

import polars as pl

DATA = Path.home() / "mtg-data/17lands/DSK"
REPO = Path(__file__).resolve().parent.parent
TESTS = ["hand", "order", "timing", "targets", "blocks", "guests"]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--games", type=int, default=20000); ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    cards = pl.read_csv(DATA.parent / "cards.csv")
    raw = dict(zip(cards["id"], cards["name"]))
    full = {h: n for n in raw.values() if " // " in n for h in n.split(" // ")}
    name = {i: full.get(n, n) for i, n in raw.items()}
    abil = pl.read_csv(DATA.parent / "abilities.csv")
    abil_target = {i: "target" in (t or "").lower() for i, t in zip(abil["id"], abil["text"])}
    text = {c["name"]: " ".join(c["rules"] + c.get("left", {}).get("rules", []) + c.get("right", {}).get("rules", []))
            for c in json.loads((REPO / "engine/vocab/dsk_card_text.json").read_text())}
    dsk = set(text)
    targeted = lambda n: "target" in text.get(n, "target")  # cards we have no text for count as targeted

    def ids(v):
        return [] if v in (None, "") else [int(x) for x in str(v).split("|") if x]

    def names(v):
        return [name.get(i, str(i)) for i in ids(v)]

    lf = pl.scan_parquet(DATA / "parquet/replay_data.parquet")
    n = lf.select(pl.len()).collect().item()
    rows = sorted(random.Random(a.seed).sample(range(n), min(a.games, n)))
    df = lf.with_row_index("row").filter(pl.col("row").is_in(rows)).collect()
    deck_cols = [c for c in df.columns if c.startswith("deck_")]

    fails = collections.Counter(); only = collections.Counter(); passed = 0; total = 0
    for g in df.iter_rows(named=True):
        total += 1
        bad = set()
        if any(g[c] and c[5:] not in dsk for c in deck_cols): bad.add("guests")
        order = [(s, t) for t in range(1, 31) for s in (("user", "oppo") if g["on_play"] else ("oppo", "user"))]
        hand = collections.Counter(names(g["opening_hand"]))
        for side, t in order:
            if t > (g["num_turns"] or 0):
                break
            p = f"{side}_turn_{t}_"
            active_spells = names(g[p + "creatures_cast"]) + names(g[p + "non_creatures_cast"])
            user_inst, oppo_inst = names(g[p + "user_instants_sorceries_cast"]), names(g[p + "oppo_instants_sorceries_cast"])
            if side == "user":
                user_plays = list((collections.Counter(active_spells) | collections.Counter(user_inst)).elements())
                oppo_plays = oppo_inst
            else:
                oppo_plays = list((collections.Counter(active_spells) | collections.Counter(oppo_inst)).elements())
                user_plays = user_inst
            ua, oa = ids(g[p + "user_abilities"]), ids(g[p + "oppo_abilities"])
            if len(user_plays) + len(ua) >= 2 or len(oppo_plays) + len(oa) >= 2: bad.add("order")
            active_plays = user_plays if side == "user" else oppo_plays
            if active_plays and g[p + "creatures_attacked"]: bad.add("timing")
            if any(targeted(c) for c in user_plays + oppo_plays) or any(abil_target.get(x, True) for x in ua + oa): bad.add("targets")
            if len(ids(g[p + "creatures_attacked"])) >= 2 and ids(g[p + "creatures_blocking"]): bad.add("blocks")
            # hand tracking (user)
            if side == "user":
                hand += collections.Counter(names(g[p + "cards_drawn"]) + names(g[p + "cards_tutored"]))
                hand -= collections.Counter(names(g[p + "lands_played"]) + user_plays + names(g[p + "cards_discarded"]))
            else:
                hand -= collections.Counter(user_inst)
            truth = collections.Counter(names(g[p + "eot_user_cards_in_hand"]))
            if hand != truth:
                bad.add("hand"); hand = truth
        for b in bad: fails[b] += 1
        if len(bad) == 1: only[next(iter(bad))] += 1
        passed += not bad
    pct = lambda x: round(100 * x / total, 1)
    out = {"sample_games": total, "seed": a.seed, "fully_replayable_pct": pct(passed), "fully_replayable_games": passed,
           "fail_pct_by_test": {k: pct(fails[k]) for k in TESTS},
           "games_failing_only_this_test_pct": {k: pct(only[k]) for k in TESTS}}
    (DATA / "replayable.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
