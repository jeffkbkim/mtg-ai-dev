"""Summarise a soak directory: per-card exposure and problems, and a short markdown report.

    uv run python experiments/coverage_soak/report.py ~/mtg-data/soak/<name>

Writes cards.json and report.md into that directory and prints the report.
"""
import collections, json, re, sys
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent.parent


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main(root):
    root = Path(root)
    runs = [json.loads((p / "run.json").read_text()) for p in sorted((root / "runs").iterdir()) if (p / "run.json").exists()]
    names = [c["name"] for c in json.loads((REPO / "engine/vocab/dsk_card_text.json").read_text())]
    by_class = {norm(n): n for n in names}
    cards = {n: {"decks": 0, "runs_seen_in_play": 0, "problem_runs": 0, "issues": collections.Counter()} for n in names}
    statuses, games, terminal, turn_limit = collections.Counter(), 0, 0, 0
    totals = collections.Counter()
    for r in runs:
        statuses[r["status"]] += 1
        in_run = set(r["cards"]["py"]) | set(r["cards"]["ai"])
        for side in ("py", "ai"):
            for n in r["cards"][side]:
                cards[n]["decks"] += 1
        for n in r["seen_in_play"]:
            if n in cards:
                cards[n]["runs_seen_in_play"] += 1
        for g in r["results"]:
            games += 1
            terminal += g.get("terminal") == "true"
        expected = int(json.loads((root / "config.json").read_text())["games"])
        issues = []  # (card or None, text)
        if r["status"] != "ok":
            issues.append((None, f"run {r['status']}"))
        if len(r["results"]) < expected:
            issues.append((None, f"only {len(r['results'])}/{expected} games finished"))
        for g in r["results"]:
            if g.get("terminal") != "true":
                issues.append((None, f"game {g.get('game')} not finished after {g.get('turns')} turns"))
        for e in r["exceptions"]:
            hit = [by_class[c.lower()] for c in e["card_frames"] if c.lower() in by_class]
            for n in hit or [None]:
                issues.append((n, "exception: " + e["line"][:160]))
        c = r["counters"]
        for key in ("LEAKS", "UNMAPPED_ABILITIES", "UNMAPPED_CHOICES", "UNKEYED_ON_BOARD"):
            v = c.get(key, "{}").strip()
            if v not in ("{}", "0", ""):
                totals[key] += 1
                named = [n for n in in_run if n in v]
                for n in named or [None]:
                    issues.append((n, f"{key}: {v[:200]}"))
        rej = c.get("REJECTED", "0").split(" ", 1)
        if rej[0] != "0":
            totals["REJECTED"] += 1
            named = [n for n in in_run if n in rej[1]]
            for n in named or [None]:
                issues.append((n, f"REJECTED: {rej[1][:200]}"))
        if issues:
            r["issues"] = issues
            for n in in_run:
                cards[n]["problem_runs"] += 1
            for n, text in issues:
                if n:
                    cards[n]["issues"][text] += 1
    named = {n: v for n, v in cards.items() if v["issues"]}
    untested = sorted(n for n, v in cards.items() if v["decks"] and not v["runs_seen_in_play"])
    never = sorted(n for n, v in cards.items() if not v["decks"])
    unattributed = [(r["run"], r["decks"], [t for n, t in r["issues"] if n is None]) for r in runs if any(n is None for n, _ in r.get("issues", []))]
    out = {n: {**v, "issues": dict(v["issues"])} for n, v in cards.items()}
    (root / "cards.json").write_text(json.dumps(out, indent=1))
    lines = [f"# Soak report: {root.name}", "",
             f"{len(runs)} runs, {games} games, {terminal} finished normally. Run status: {dict(statuses)}.",
             f"Runs with each problem: {dict(totals) or 'none'}.", "",
             f"## Cards with problems attributed to them ({len(named)})", ""]
    for n, v in sorted(named.items(), key=lambda kv: -sum(kv[1]['issues'].values())):
        lines.append(f"- **{n}** (in {v['decks']} decks, reached play in {v['runs_seen_in_play']} runs)")
        for text, k in v["issues"].most_common(3):
            lines.append(f"  - {k}x {text}")
    lines += ["", f"## Problems not tied to one card ({len(unattributed)} runs)", ""]
    for run, decks, texts in unattributed[:30]:
        lines.append(f"- run {run} ({decks['py']} vs {decks['ai']}): " + "; ".join(sorted(set(texts)))[:300])
    # cards that keep showing up in problem runs, relative to how often they were played
    suspects = sorted(((v["problem_runs"] / v["decks"], n, v) for n, v in cards.items() if v["decks"] >= 3 and v["problem_runs"]), reverse=True)[:15]
    if unattributed:
        lines += ["", "## Cards most often in those runs (share of their decks)", ""]
        lines += [f"- {n}: {v['problem_runs']}/{v['decks']}" for share, n, v in suspects]
    lines += ["", f"## In a deck but never reached the battlefield or stack ({len(untested)})", "", ", ".join(untested) or "none",
              "", f"## Never in a deck ({len(never)})", "", ", ".join(never) or "none", ""]
    (root / "report.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1])
