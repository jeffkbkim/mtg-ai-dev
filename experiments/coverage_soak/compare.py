"""Compare two soak directories and list what got worse.

    uv run python experiments/coverage_soak/compare.py <baseline dir> <new dir>

Prints a short markdown summary. Its first line is "NEW PROBLEMS" when the new soak has crashes, hangs, games
that didn't finish, leak reports, more runs with unmapped abilities or choices than the baseline, or 20% more
refused moves; otherwise "NO NEW PROBLEMS".
"""
import glob, json, re, sys
from pathlib import Path


def stats(d):
    rs = [json.loads(Path(p).read_text()) for p in glob.glob(f"{d}/runs/*/run.json")]
    games_expected = json.loads((Path(d) / "config.json").read_text())["games"] * len(rs)
    s = {"runs": len(rs), "games": sum(len(r["results"]) for r in rs), "games_expected": games_expected,
         "unfinished_games": sum(g.get("terminal") != "true" for r in rs for g in r["results"]),
         "bad_runs": sum(r["status"] != "ok" for r in rs),
         "crashes": sum("Exception in thread" in e["line"] for r in rs for e in r["exceptions"]),
         "leak_runs": sum(r["counters"].get("LEAKS", "{}") != "{}" for r in rs),
         "unmapped_runs": sum(r["counters"].get(k, "{}") != "{}" for r in rs for k in ("UNMAPPED_ABILITIES", "UNMAPPED_CHOICES")),
         "refused": sum(int(r["counters"].get("REJECTED", "0").split(" ", 1)[0]) for r in rs),
         "simulated": sum(int(r["counters"].get("SIMULATED", "0") or 0) for r in rs)}
    s["leaks"] = sorted({m for r in rs for m in re.findall(r"name in message: ([^=,}]+)", r["counters"].get("LEAKS", ""))})
    return s


def main(base, new):
    b, n = stats(base), stats(new)
    worse = []
    if n["crashes"]: worse.append(f"{n['crashes']} crashes")
    if n["bad_runs"]: worse.append(f"{n['bad_runs']} runs hung or closed early")
    if n["games"] < n["games_expected"] or n["unfinished_games"]: worse.append(f"{n['games']}/{n['games_expected']} games played, {n['unfinished_games']} unfinished")
    if n["leak_runs"]: worse.append(f"leak reports in {n['leak_runs']} runs: {', '.join(n['leaks'])}")
    if n["unmapped_runs"] > b["unmapped_runs"]: worse.append(f"runs with unmapped abilities/choices {b['unmapped_runs']} -> {n['unmapped_runs']}")
    if n["refused"] > 1.2 * b["refused"]: worse.append(f"refused moves {b['refused']} -> {n['refused']}")
    print("NEW PROBLEMS" if worse else "NO NEW PROBLEMS")
    for w in worse: print(f"- {w}")
    print()
    print("| | baseline | new |\n|---|---:|---:|")
    for k in ("games", "crashes", "bad_runs", "leak_runs", "unmapped_runs", "refused", "simulated"):
        print(f"| {k} | {b[k]} | {n[k]} |")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
