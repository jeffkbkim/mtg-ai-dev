"""Colour-pair win rates from 17lands' public game data, in the shape of 17lands' color_ratings endpoint
(combine_splash=true), for sets whose ratings page we can't fetch (the cloud can't reach 17lands.com).

  python3 play/color_ratings_17lands.py <game_data_public.<SET>.PremierDraft.csv.gz> <out json>

One row per main-colour combination ({"short_name", "wins", "games", "is_summary": false}) and one summary row per
number of main colours ("is_summary": true), all games of the file. A splash doesn't change the row (combine_splash).
"""
import csv, gzip, json, sys
from collections import Counter


def main(data, out):
    games, wins = Counter(), Counter()
    with gzip.open(data, "rt", newline="") as f:
        r = csv.reader(f)
        col = {h: i for i, h in enumerate(next(r))}
        for row in r:
            c = row[col["main_colors"]]
            games[c] += 1
            wins[c] += row[col["won"]] == "True"
    rows = [{"short_name": c, "wins": wins[c], "games": games[c], "is_summary": False}
            for c in sorted(games, key=lambda c: (len(c), c)) if c]
    for k in sorted({len(c) for c in games if c}):
        cs = [c for c in games if len(c) == k]
        rows.append({"short_name": f"{k} colors", "wins": sum(wins[c] for c in cs), "games": sum(games[c] for c in cs),
                     "is_summary": True})
    with open(out, "w") as f:
        json.dump(rows, f, indent=1)
    for x in rows:
        if len(x["short_name"]) == 2 and not x["is_summary"]:
            print(f"{x['short_name']} {x['wins'] / x['games']:.1%} of {x['games']}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
