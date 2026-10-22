"""How much of a 17lands DSK replay is an exact record of the player's decisions, and how much would be inferred?

    uv run --group data python seventeenlands/replay_check.py [--games 20000] [--seed 0]

Reads a random sample of replay_data.parquet (see prepare.py) and measures, per decision type, whether the replay
pins down the choice exactly or leaves parts to guess:
  - mulligans: every candidate hand is recorded -> keep/mulligan is exact
  - hand tracking: rebuild the hand from the opening hand, draws and plays, and compare with the end-of-turn hand
    17lands records. Where they agree, the cards available to each decision are known.
  - land drops and attacks: the chosen card(s) are recorded as sets -> exact
  - spells: which cards were cast each turn is recorded, but not their order, timing within the turn, or targets
  - blocks: which creatures blocked is recorded, but not which attacker each one blocked
Writes replay_check.json next to the data and prints a summary.
"""
import argparse, collections, json, random
from pathlib import Path

import polars as pl

DATA = Path.home() / "mtg-data/17lands/DSK"
REPO = Path(__file__).resolve().parent.parent
MAX_TURN = 30


def ids(v):
    return [] if v in (None, "") else [int(x) for x in str(v).split("|") if x]


def names(v, name):
    return [name.get(i, str(i)) for i in ids(v)]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--games", type=int, default=20000); ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    cards = pl.read_csv(DATA.parent / "cards.csv")
    raw = dict(zip(cards["id"], cards["name"]))
    # 17lands gives a split card / Room's halves their own ids ("Glassworks"); count them as the whole card
    full = {}
    for n in raw.values():
        if " // " in n:
            for half in n.split(" // "): full[half] = n
    name = {i: full.get(n, n) for i, n in raw.items()}
    rules = {c["name"]: " ".join(c["rules"]) + " ".join(c.get("left", {}).get("rules", []) + c.get("right", {}).get("rules", []))
             for c in json.loads((REPO / "engine/vocab/dsk_card_text.json").read_text())}
    targets = lambda n: "target" in rules.get(n, "")  # cards outside the DSK list (special guests) count as no target

    lf = pl.scan_parquet(DATA / "parquet/replay_data.parquet")
    n = lf.select(pl.len()).collect().item()
    rows = sorted(random.Random(a.seed).sample(range(n), min(a.games, n)))
    df = lf.with_row_index("row").filter(pl.col("row").is_in(rows)).collect()

    c = collections.Counter()
    left_unrecorded, came_unrecorded = collections.Counter(), collections.Counter()
    for g in df.iter_rows(named=True):
        c["games"] += 1
        hands = [g[f"candidate_hand_{i}"] for i in range(1, 8) if g[f"candidate_hand_{i}"]]
        c["mulligan_decisions"] += len(hands)
        c["mulligan_hands_recorded_ok"] += len(hands) == (g["num_mulligans"] or 0) + 1
        order = [("user", t) if first == "user" else ("oppo", t) for t in range(1, MAX_TURN + 1)
                 for first in (("user", "oppo") if g["on_play"] else ("oppo", "user"))]
        hand = collections.Counter(names(g["opening_hand"], name))
        tracked = True
        for side, t in order:
            p = f"{side}_turn_{t}_"
            if t > (g["num_turns"] or 0):
                continue  # turn not reached
            mine = side == "user"
            if mine:
                hand += collections.Counter(names(g[p + "cards_drawn"], name) + names(g[p + "cards_tutored"], name))
                # an instant cast on your own turn is listed under instants_sorceries, sometimes also non_creatures
                spells = collections.Counter(names(g[p + "non_creatures_cast"], name)) | collections.Counter(names(g[p + "user_instants_sorceries_cast"], name))
                played = names(g[p + "lands_played"], name) + names(g[p + "creatures_cast"], name) + list(spells.elements()) + names(g[p + "cards_discarded"], name)
                lands, cast = names(g[p + "lands_played"], name), names(g[p + "creatures_cast"], name) + list(spells.elements())
                c["user_turns"] += 1
                c["land_drops"] += len(lands)
                c["spells_cast"] += len(cast)
                c["spells_needing_targets"] += sum(map(targets, cast))
                c["turns_with_2plus_spells"] += len(cast) >= 2
                att, blocked = ids(g[p + "creatures_attacked"]), ids(g[p + "creatures_blocked"])
                c["turns_with_attacks"] += bool(att)
                blockers = ids(g["oppo_turn_%d_creatures_blocking" % t]) if g.get("oppo_turn_%d_creatures_blocking" % t) else []
            else:
                # on the opponent's turn the user can only cast instants (and flash); the replay lists those
                played = names(g[p + "user_instants_sorceries_cast"], name)
                c["instants_on_opponent_turn"] += len(played)
                att, blk = ids(g[p + "creatures_attacked"]), ids(g[p + "creatures_blocking"])
                if blk:
                    c["turns_with_user_blocks"] += 1
                    c["user_blocks_assignment_ambiguous"] += len(att) > 1 and len(blk) >= 1
            hand -= collections.Counter(played)
            truth = collections.Counter(names(g[p + "eot_user_cards_in_hand"], name))
            c[f"{side}_turn_hand_checks"] += 1
            if hand == truth:
                c[f"{side}_turn_hand_matches"] += 1
            else:
                tracked = False
                for k in (hand - truth).elements(): left_unrecorded[k] += 1   # left the hand with no record
                for k in (truth - hand).elements(): came_unrecorded[k] += 1   # came into the hand with no record
                hand = truth  # resync on the recorded hand and keep going
        c["games_hand_tracked_whole_game"] += tracked

    pct = lambda x, y: round(100 * c[x] / max(1, c[y]), 1)
    out = {"sample_games": c["games"], "seed": a.seed, "counts": dict(c), "percent": {
        "mulligan hands all recorded": pct("mulligan_hands_recorded_ok", "games"),
        "user turns where rebuilt hand = recorded hand": pct("user_turn_hand_matches", "user_turn_hand_checks"),
        "opponent turns where rebuilt hand = recorded hand": pct("oppo_turn_hand_matches", "oppo_turn_hand_checks"),
        "games with hand tracked all game": pct("games_hand_tracked_whole_game", "games"),
        "user turns with 2+ spells (order unknown)": pct("turns_with_2plus_spells", "user_turns"),
        "spells whose card text has a target (target unknown)": pct("spells_needing_targets", "spells_cast"),
        "user block turns facing 2+ attackers (assignment unknown)": pct("user_blocks_assignment_ambiguous", "turns_with_user_blocks")},
        "hand mismatches": {"left hand with no record (top)": left_unrecorded.most_common(12),
                            "came into hand with no record (top)": came_unrecorded.most_common(12)}}
    (DATA / "replay_check.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
