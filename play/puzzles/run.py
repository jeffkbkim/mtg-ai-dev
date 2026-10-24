"""Ask the Claude player the frozen decisions in puzzles.jsonl under several prompt versions (primer v1 / v2).

Each sample is a fresh ClaudePlayer (Playmat's settings: claude-opus-5-5, effort high, facts, self-check, no plan)
whose game log is set to what that seat had seen before the decision, so the first message is the usual
"The game continues ... Game log so far:" restart followed by the decision (mulligans get "A new game starts.").
The log, including the original player's earlier reasons, is identical for every primer.

Results are appended to results/results.jsonl, one line per (puzzle, primer, sample); a rerun skips what is there.

    python play/puzzles/run.py --samples 1 --ids bad-4741-87 ctl-18de-8   # try a few first, see the cost
    python play/puzzles/run.py --samples 2 --budget 8                     # the rest, stops starting jobs past $8
    python play/puzzles/run.py --report                                   # per-puzzle table and totals (markdown)
"""
import argparse, json, shutil, sys, threading, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from players import ClaudePlayer  # noqa: E402
from render import option_label  # noqa: E402

RESULTS = HERE / "results" / "results.jsonl"
SETTINGS = dict(model="claude-opus-5-5", effort="high", facts=True, check=True)
_lock = threading.Lock()


def load_puzzles():
    return [json.loads(l) for l in (HERE / "puzzles.jsonl").open()]


def load_results():
    if not RESULTS.exists():
        return []
    return [json.loads(l) for l in RESULTS.open() if l.strip()]


def ask(p, primer):
    """One sample: (choice, info) from a fresh player that has this seat's log."""
    pl = ClaudePlayer(primer=primer, **SETTINGS)
    pl.start_game(0, p["deck"])
    pl.log = list(p["log"])
    pl.prev_obs = p["obs"]  # the log already holds what changed up to this decision
    pl.asked_any = bool(pl.log)
    pl.checked_combat = tuple(p["checked_combat"]) if p["checked_combat"] else None
    msg = {k: p[k] for k in ("kind", "prompt", "obs", "options", "leaks")}
    try:
        return pl.choose(msg), pl.prompt_sha
    finally:
        pl.end_game(None)
        shutil.rmtree(pl.workdir, ignore_errors=True)


def run_group(p, primer, samples, done, budget, spent):
    for s in range(samples):
        if (p["id"], primer, s) in done:
            continue
        with _lock:
            if spent[0] >= budget:
                print(f"budget reached (${spent[0]:.2f}), skipping {p['id']} {primer} s{s}", flush=True)
                return
        t0 = time.time()
        try:
            (choice, info), sha = ask(p, primer)
        except Exception as e:  # recorded, never hidden
            print(f"{p['id']} {primer} s{s}: ERROR {e}", flush=True)
            continue
        cost = sum(t.get("cost_usd") or 0.0 for t in info.get("turns", []))
        sc = info.get("self_check") or {}
        row = {"id": p["id"], "primer": primer, "sample": s, "choice": choice,
               "label": option_label(p["options"][choice], p["obs"]["entries"]), "reason": info.get("reason"),
               "invalid": info.get("invalid", False), "self_check_first": sc.get("first_choice"),
               "self_check_first_reason": sc.get("first_reason"), "cost_usd": round(cost, 4),
               "seconds": round(time.time() - t0, 1), "prompt_sha": sha, "settings": SETTINGS,
               "ok": choice in p["acceptable"], "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with _lock:
            spent[0] += cost
            RESULTS.parent.mkdir(exist_ok=True)
            with RESULTS.open("a") as f:
                f.write(json.dumps(row) + "\n")
            print(f"{p['id']} {primer} s{s}: {choice} ({row['label'][:40]}) {'OK' if row['ok'] else 'WRONG'} "
                  f"${cost:.3f} {row['seconds']}s  total ${spent[0]:.2f}", flush=True)


def report():
    """Per-puzzle table and totals; OK is recomputed from puzzles.jsonl (acceptable, and lenient where given)."""
    puzzles = load_puzzles()
    res = defaultdict(list)
    for r in load_results():
        res[(r["id"], r["primer"])].append(r)
    cost = sum(r["cost_usd"] for v in res.values() for r in v)
    n = sum(len(v) for v in res.values())
    lines = ["| Puzzle | Type | Kind | Orig | Acceptable | v1 picks | v2 picks | v1 OK | v2 OK | lenient v1 / v2 |",
             "|---" * 10 + "|"]
    tally = defaultdict(int)
    for p in puzzles:
        a = sorted(res[(p["id"], "v1")], key=lambda r: r["sample"])
        b = sorted(res[(p["id"], "v2")], key=lambda r: r["sample"])
        if not a or not b:
            continue
        ok = lambda rows, s: sum(r["choice"] in s for r in rows)
        ok1, ok2 = ok(a, p["acceptable"]), ok(b, p["acceptable"])
        len_ = f"{ok(a, p['lenient'])}/{len(a)} / {ok(b, p['lenient'])}/{len(b)}" if p.get("lenient") else ""
        lines.append(f"| {p['id']} | {p['type']} | {p['kind']} | {p['original']['choice']} | {p['acceptable']} | "
                     f"{' '.join(str(r['choice']) for r in a)} | {' '.join(str(r['choice']) for r in b)} | "
                     f"{ok1}/{len(a)} | {ok2}/{len(b)} | {len_} |")
        f1, f2 = ok1 / len(a), ok2 / len(b)
        tally[f"{p['type']}: v2 " + ("better" if f2 > f1 else "worse" if f2 < f1 else "same")] += 1
        if f1 < 0.5 <= f2:
            tally[f"{p['type']}: fixed by v2 (v1 mostly wrong, v2 mostly right)"] += 1
        if f1 >= 0.5 > f2:
            tally[f"{p['type']}: broken by v2 (v1 mostly right, v2 mostly wrong)"] += 1
    for primer in ("v1", "v2"):
        for typ in ("bad", "control"):
            rows = [(p, r) for p in puzzles if p["type"] == typ for r in res[(p["id"], primer)]]
            if rows:
                tally[f"{primer} {typ}: samples OK"] = f"{sum(r['choice'] in p['acceptable'] for p, r in rows)}/{len(rows)}"
    print("\n".join(lines))
    print()
    for k, v in sorted(tally.items()):
        print(f"- {k}: {v}")
    print(f"- samples: {n}, cost ${cost:.2f}, mean ${cost / max(n, 1):.3f} per sample")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--primers", default="v1,v2")
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--budget", type=float, default=8.0, help="stop starting samples once results.jsonl totals this (USD)")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.report:
        return report()
    old = load_results()
    done = {(r["id"], r["primer"], r["sample"]) for r in old}
    spent = [sum(r["cost_usd"] for r in old)]
    puzzles = [p for p in load_puzzles() if not a.ids or p["id"] in a.ids]
    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(run_group, p, pr, a.samples, done, a.budget, spent)
                for p in puzzles for pr in a.primers.split(",")]
        for f in futs:
            f.result()
    print(f"total spent ${spent[0]:.2f}")


if __name__ == "__main__":
    main()
