"""Per main-color-pair stats from 17lands DSK game data, for play/primer/dsk_meta_v2.md. One streaming pass.

Usage: python archetype_stats_17lands.py game_data_public.DSK.PremierDraft.csv.gz cards.csv out.json
Per two-color main_colors pair: games, win rate, mean num_turns, mean creatures and nonland cards per deck, mean
nonland mana value, and per card: games with it in the deck, mean copies, games in hand and wins (GIH).
"""
import csv, gzip, sys, json, collections

path, cards_path, out = sys.argv[1:4]
info = {}
with open(cards_path) as f:
    for r in csv.DictReader(f):
        if r["expansion"] == "DSK" or r["name"] not in info:
            info[r["name"]] = r
for n, r in list(info.items()):  # a Room's row carries both doors' total mana value; count the cheaper door
    if " // " in n and all(h in info for h in n.split(" // ")):
        info[n] = dict(r, mana_value=min(float(info[h]["mana_value"]) for h in n.split(" // ")))
with gzip.open(path, "rt") as f:
    r = csv.reader(f)
    h = next(r)
    ix = {c: i for i, c in enumerate(h)}
    names = [c[len("deck_"):] for c in h if c.startswith("deck_")]
    cols = [(n, ix["opening_hand_" + n], ix["drawn_" + n], ix["deck_" + n]) for n in names]
    def kind(n):
        t = info.get(n, {}).get("types", "")
        return ("land" if "Land" in t and "Creature" not in t else "creature" if "Creature" in t else "spell"), float(info.get(n, {}).get("mana_value") or 0)
    kinds = {n: kind(n) for n in names}
    won_i, mc_i, nt_i = ix["won"], ix["main_colors"], ix["num_turns"]
    P = collections.defaultdict(lambda: {"games": 0, "wins": 0, "turns": 0, "creatures": 0, "nonland": 0, "mv": 0.0,
                                         "deck": collections.Counter(), "copies": collections.Counter(),
                                         "gih": collections.Counter(), "gihw": collections.Counter()})
    for row in r:
        mc = row[mc_i]
        if len(mc) != 2:
            continue
        p = P[mc]
        w = row[won_i] == "True"
        p["games"] += 1; p["wins"] += w; p["turns"] += int(row[nt_i] or 0)
        for name, oh, dr, dk in cols:
            k = row[dk]
            if k != "0" and k != "":
                c = int(k)
                kd, mv = kinds[name]
                if kd != "land":
                    p["nonland"] += c; p["mv"] += c * mv
                    if kd == "creature":
                        p["creatures"] += c
                p["deck"][name] += 1; p["copies"][name] += c
                if row[oh] != "0" or row[dr] != "0":
                    p["gih"][name] += 1; p["gihw"][name] += w
res = {}
for mc, p in P.items():
    g = p["games"]
    res[mc] = {"games": g, "wr": p["wins"] / g, "avg_turns": p["turns"] / g, "avg_creatures": p["creatures"] / g,
               "avg_nonland": p["nonland"] / g, "avg_mv": p["mv"] / max(p["nonland"], 1),
               "cards": {n: {"deck_games": p["deck"][n], "copies": p["copies"][n] / g, "gih": p["gih"][n],
                             "gih_wr": p["gihw"][n] / p["gih"][n] if p["gih"][n] else None} for n in p["deck"]}}
json.dump(res, open(out, "w"), indent=0)
print({k: v["games"] for k, v in sorted(res.items(), key=lambda x: -x[1]["games"])})
