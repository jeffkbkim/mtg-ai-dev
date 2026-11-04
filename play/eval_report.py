"""Win rates with 95% intervals for play/eval_games.py runs.

    python3 play/eval_report.py <run dir> [<run dir> ...] [--json out.json]

Per run: games, wins / losses / unfinished, win rate with a 95% Wilson interval, the same split by on the play / on
the draw, and how many of the policy's decisions fell back to a random legal option (the encoder could not map them).

Two intervals, because games are not fully independent:
- Wilson: treats every game as an independent coin flip. Better than "p +- 1.96 * sqrt(p(1-p)/n)" near 0% or 100%,
  where that formula can go below 0 or above 1.
- bootstrap by deck pair: the four games of a deck pair share decks, so they are correlated (a deck pair that favours
  nobody still has one deck with better cards). Resampling whole pairs keeps that; if it is much wider than Wilson,
  deck luck matters and more pairs would help more than more games per pair.

A game with no winner (turn 100 cap, both players lost, an engine error) counts as not a win, and is listed.
"""
import argparse, json, math, random
from collections import defaultdict
from pathlib import Path


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = wins / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def pair_bootstrap(games: list[dict], reps: int = 5000, seed: int = 0) -> tuple[float, float]:
    by_pair = defaultdict(list)
    for g in games:
        by_pair[g["pair"]].append(g["winner"] == "A")
    pairs = list(by_pair.values())
    if len(pairs) < 2:
        return 0.0, 1.0
    rng = random.Random(seed)
    rates = []
    for _ in range(reps):
        sample = [r for _ in pairs for r in rng.choice(pairs)]
        rates.append(sum(sample) / len(sample))
    rates.sort()
    return rates[int(0.025 * reps)], rates[int(0.975 * reps) - 1]


def summarize(run: Path) -> dict:
    cfg = json.loads((run / "config.json").read_text())
    games = [json.loads(line) for line in (run / "games.jsonl").read_text().splitlines() if line.strip()]
    n = len(games)
    wins = sum(g["winner"] == "A" for g in games)
    losses = sum(g["winner"] == "B" for g in games)
    out = {
        "run": str(run), "policy": cfg.get("policy_meta", {}).get("name"), "opponent": cfg["opponent"],
        "scheduled": cfg["games"], "games": n, "wins": wins, "losses": losses, "no_winner": n - wins - losses,
        "win_rate": wins / n if n else None, "wilson95": wilson(wins, n), "pair_bootstrap95": pair_bootstrap(games),
        "decisions": sum(g["decisions"] for g in games), "fallbacks": sum(g["fallbacks"] for g in games),
        "mean_turns": sum(g["turns"] for g in games) / n if n else None,
        "code_commit": cfg.get("code_commit"), "checkpoint_sha256": cfg.get("policy_meta", {}).get("checkpoint_sha256"),
        "seed": cfg.get("seed"),
    }
    for side, label in (("A", "on_the_play"), ("B", "on_the_draw")):
        sub = [g for g in games if g["first"] == side]
        w = sum(g["winner"] == "A" for g in sub)
        out[label] = {"games": len(sub), "wins": w, "wilson95": wilson(w, len(sub))}
    # a behaviour check that needs no opponent: in its own first main phase, with a land drop left and a land it can
    # play, how often does the policy pass instead? (the first such window of each turn)
    windows = {}
    for f in sorted(run.glob("part*/decisions.jsonl")):
        for line in f.read_text().splitlines():
            d = json.loads(line)
            if (d.get("kind") == "PRIORITY" and d.get("my_turn") and d.get("step") == "Precombat Main"
                    and d.get("lands_played") == 0 and "PLAY_LAND" in d.get("offered", [])):
                windows.setdefault((f.parent.name, d["game"], d["turn"]), d["label"])
    out["land_windows"] = len(windows)
    out["land_windows_passed"] = sum(label == "PASS" for label in windows.values())
    out["no_winner_games"] = [{k: g.get(k) for k in ("part", "game", "turns", "error")}
                              for g in games if g["winner"] not in ("A", "B")]
    return out


def show(s: dict) -> str:
    pct = lambda x: f"{100 * x:.1f}%"
    lo, hi = s["wilson95"]
    blo, bhi = s["pair_bootstrap95"]
    lines = [f"{s['policy']} vs {s['opponent']}: {s['wins']}-{s['losses']}"
             + (f" ({s['no_winner']} no winner)" if s["no_winner"] else "")
             + f" in {s['games']}/{s['scheduled']} games",
             f"  win rate {pct(s['win_rate'])}  95% Wilson [{pct(lo)}, {pct(hi)}]  "
             f"deck-pair bootstrap [{pct(blo)}, {pct(bhi)}]"]
    for label in ("on_the_play", "on_the_draw"):
        r = s[label]
        if r["games"]:
            a, b = r["wilson95"]
            lines.append(f"  {label.replace('_', ' '):<12} {r['wins']}/{r['games']} = {pct(r['wins'] / r['games'])}"
                         f"  [{pct(a)}, {pct(b)}]")
    if s["decisions"]:
        lines.append(f"  policy decisions {s['decisions']}, random fallbacks {s['fallbacks']} "
                     f"({pct(s['fallbacks'] / s['decisions'])}), mean game length {s['mean_turns']:.1f} turns")
    if s["land_windows"]:
        lines.append(f"  first main phase with a land drop available: passed {s['land_windows_passed']}/"
                     f"{s['land_windows']} ({pct(s['land_windows_passed'] / s['land_windows'])})")
    lines.append(f"  commit {s['code_commit'][:10]}, checkpoint {str(s['checkpoint_sha256'])[:12]}, seed {s['seed']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    summaries = [summarize(r) for r in args.runs]
    print("\n\n".join(show(s) for s in summaries))
    if args.json:
        args.json.write_text(json.dumps(summaries, indent=1))


if __name__ == "__main__":
    main()
