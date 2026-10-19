import csv, gzip, sys, json, collections
path, out = sys.argv[1], sys.argv[2]
with gzip.open(path, "rt") as f:
    r = csv.reader(f)
    h = next(r)
    names = [c[len("deck_"):] for c in h if c.startswith("deck_")]
    ix = {c: i for i, c in enumerate(h)}
    won_i, colors_i, rank_i = ix["won"], ix["main_colors"], ix["rank"]
    cols = [(n, ix["opening_hand_" + n], ix["drawn_" + n], ix["deck_" + n]) for n in names]
    gih = collections.Counter(); gihw = collections.Counter(); deck = collections.Counter(); deckw = collections.Counter()
    pair = collections.Counter(); pairw = collections.Counter(); n = 0; nw = 0
    for row in r:
        n += 1
        w = row[won_i] == "True"; nw += w
        c = row[colors_i]
        pair[c] += 1; pairw[c] += w
        for name, oh, dr, dk in cols:
            if row[dk] != "0":
                deck[name] += 1; deckw[name] += w
                if row[oh] != "0" or row[dr] != "0":
                    gih[name] += 1; gihw[name] += w
res = {"games": n, "win_rate": nw / n,
       "cards": {k: {"gih_games": gih[k], "gih_wr": gihw[k] / gih[k] if gih[k] else None, "deck_games": deck[k]} for k in names},
       "colors": {k: {"games": pair[k], "wr": pairw[k] / pair[k]} for k in pair}}
json.dump(res, open(out, "w"), indent=1)
print(n, nw / n)
