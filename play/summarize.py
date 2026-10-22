"""Summarize a play/match.py run: results, and per decision / per game time, tokens and cost for Claude seats.

  python3 play/summarize.py /mnt/project-files/claude-games/<run>
"""
import json, statistics, sys
from pathlib import Path

run = Path(sys.argv[1])
games = [json.loads(l) for l in (run / "games.jsonl").read_text().splitlines()]
print(f"{len(games)} games: " + ", ".join(f"g{g['game']} first={g['first']} winner={g['winner']} turns={g['turns']} life A/B={g['life_a']}/{g['life_b']}" for g in games))
for seat in "AB":
    wins = sum(g["winner"] == seat for g in games)
    print(f"seat {seat} ({games[0][seat.lower()]}): {wins}/{len(games)} wins")

FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
per_game = []
dec = []
for g in games:
    recs = []
    for l in (run / f"game{g['game']}.jsonl").read_text().splitlines():
        try:
            recs.append(json.loads(l))
        except json.JSONDecodeError:
            print(f"game {g['game']}: unreadable record skipped ({len(l)} chars)")
    for seat in "AB":
        mine = [r for r in recs if r["seat"] == seat and "turns" in r]
        if not mine:
            continue
        tot = {f: sum(t["usage"].get(f, 0) for r in mine for t in r["turns"]) for f in FIELDS}
        tot.update(game=g["game"], seat=seat, decisions=len(mine), invalid=sum(bool(r.get("invalid")) for r in mine),
                   retries=sum(len([t for t in r["turns"] if not t.get("self_check")]) - 1 for r in mine),
                   checks=sum("self_check" in r for r in mine),
                   checks_changed=sum(bool(r.get("self_check", {}).get("changed")) for r in mine), seconds=sum(r["seconds"] for r in mine),
                   cost_usd=sum(t["cost_usd"] for r in mine for t in r["turns"]))
        per_game.append(tot)
        dec += mine

if not per_game:
    sys.exit()
print("\nper Claude seat per game:")
for p in per_game:
    print(f"  g{p['game']} seat {p['seat']}: {p['decisions']} decisions, {p['seconds'] / 60:.1f} min, "
          f"input {p['input_tokens']}, cache write {p['cache_creation_input_tokens']}, cache read {p['cache_read_input_tokens']}, "
          f"output {p['output_tokens']}, ${p['cost_usd']:.2f}, invalid {p['invalid']}, retries {p['retries']}"
          + (f", self-checks {p['checks']} ({p['checks_changed']} changed)" if p["checks"] else ""))
n = len(per_game)
mean = lambda k: sum(p[k] for p in per_game) / n
print(f"\nmean per seat-game: {mean('decisions'):.0f} decisions, {mean('seconds') / 60:.1f} min, "
      f"{mean('cache_creation_input_tokens') + mean('input_tokens'):.0f} uncached input, {mean('cache_read_input_tokens'):.0f} cache read, "
      f"{mean('output_tokens'):.0f} output, ${mean('cost_usd'):.2f}")
secs = [r["seconds"] for r in dec]
out = [sum(t["usage"].get("output_tokens", 0) for t in r["turns"]) for r in dec]
fresh = [sum(t["usage"].get("cache_creation_input_tokens", 0) + t["usage"].get("input_tokens", 0) for t in r["turns"]) for r in dec]
read = [sum(t["usage"].get("cache_read_input_tokens", 0) for t in r["turns"]) for r in dec]
print(f"per decision: median {statistics.median(secs):.1f} s (max {max(secs):.0f}), "
      f"uncached input median {statistics.median(fresh):.0f}, cache read median {statistics.median(read):.0f}, "
      f"output median {statistics.median(out):.0f} (max {max(out)}), "
      f"cost mean ${sum(t['cost_usd'] for r in dec for t in r['turns']) / len(dec):.3f}")
kinds = {}
for r in dec:
    kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
print("decisions by kind:", dict(sorted(kinds.items(), key=lambda kv: -kv[1])))
