"""Compare two Claude player variants (e.g. lessons on vs off) over one or more play/match.py runs.

  python3 play/ab_report.py /mnt/project-files/claude-games/<run>/part*

A variant is the player name recorded in games.jsonl (it carries the lessons version). Prints wins with a 95% Wilson
interval, per deck, and cheap per-seat-game behaviour numbers that a lesson might move: decking losses, attacks per
own turn, lands left untapped at the end of own turns, decisions, cost. Mistake counts need a blind review on top.
"""
import json, math, sys
from collections import defaultdict
from pathlib import Path


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def untapped_lands(obs):
    return sum(1 for e in obs["entries"] if e["kind"] == "card" and e["zone"] == "BATTLEFIELD" and e["mine"]
               and "Land" in e.get("types", "") and not e.get("tapped"))


rows = []  # one per seat per game
for run in map(Path, sys.argv[1:]):
    for g in (json.loads(l) for l in (run / "games.jsonl").read_text().splitlines()):
        recs = []
        for l in (run / f"game{g['game']}.jsonl").read_text().splitlines():
            try:
                recs.append(json.loads(l))
            except json.JSONDecodeError:
                pass
        for seat in "AB":
            mine = [r for r in recs if r["seat"] == seat]
            if not mine:
                continue
            # last observation of each of my turns: lands still untapped when the turn ended (roughly unused mana)
            last_of_turn = {}
            for r in mine:
                e0 = r["obs"]["entries"][0]
                if e0["my_turn"]:
                    last_of_turn[e0["turn"]] = r["obs"]
            attacks = sum(1 for r in mine if r["kind"] == "ATTACK" and r["options"][r["choice"]]["label"] != "DONE")
            final = mine[-1]["obs"]["entries"][0]
            lost = g["winner"] not in (None, seat)
            rows.append({
                "run": run.name, "game": g["game"], "seat": seat, "variant": g[seat.lower()], "deck": g[f"deck_{seat.lower()}"],
                "first": g["first"] == seat, "win": g["winner"] == seat, "draw": g["winner"] is None,
                "decked": lost and final["my_library"] <= 1 and g[f"life_{seat.lower()}"] > 0,
                "own_turns": len(last_of_turn), "attacks": attacks,
                "untapped_end": sum(map(untapped_lands, last_of_turn.values())) / max(1, len(last_of_turn)),
                "asked": sum(1 for r in mine if "turns" in r), "auto": sum(1 for r in mine if r.get("auto")),
                "invalid": sum(1 for r in mine if r.get("invalid")),
                "cost": sum(t["cost_usd"] for r in mine for t in r.get("turns", [])),
                "turns": g["turns"],
            })

by = defaultdict(list)
for r in rows:
    by[r["variant"]].append(r)
print(f"{len({(r['run'], r['game']) for r in rows})} games")
for v, rs in sorted(by.items()):
    n, k = len(rs), sum(r["win"] for r in rs)
    lo, hi = wilson(k, n)
    mean = lambda f: sum(r[f] for r in rs) / n
    print(f"\n{v}: {k}/{n} wins ({k / n:.0%}, 95% CI {lo:.0%}-{hi:.0%}), draws {sum(r['draw'] for r in rs)}, "
          f"decked {sum(r['decked'] for r in rs)}")
    for deck in sorted({r["deck"] for r in rs}):
        d = [r for r in rs if r["deck"] == deck]
        print(f"  on {deck}: {sum(r['win'] for r in d)}/{len(d)} wins; on the play {sum(r['win'] for r in d if r['first'])}"
              f"/{sum(r['first'] for r in d)}")
    print(f"  per game: attacks per own turn {sum(r['attacks'] for r in rs) / max(1, sum(r['own_turns'] for r in rs)):.2f}, "
          f"untapped lands at end of own turn {mean('untapped_end'):.2f}, asked {mean('asked'):.0f}, auto-passed {mean('auto'):.0f}, "
          f"invalid {sum(r['invalid'] for r in rs)}, ${mean('cost'):.2f}, game length {mean('turns'):.0f} turns")
