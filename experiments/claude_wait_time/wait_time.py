"""Where the Claude seat's thinking time goes in human-vs-Claude Playmat games (read-only analysis).

    python3 experiments/claude_wait_time/wait_time.py [~/mtg-data/playmat-games]

Reads each game folder's config.json (only games with one human and one Claude seat), the Claude seat's
seat-X.jsonl (its decisions as they happened, with `seconds`: the seat's wall-clock time from being asked to
answering, measured by the Claude service) and game0.jsonl (to drop decisions marked superseded by a take-back).
Rows with `auto` set (pass_until:..., own_stack) were answered without a model call; they are counted separately.
"""
import collections, glob, json, os, statistics, sys

COMBAT = {"Begin Combat", "Declare Attackers", "Declare Blockers", "First Strike Damage", "Combat Damage", "End Combat"}


def stack_kind(entries):
    st = [e for e in entries if e.get("zone") == "STACK"]
    if not st:
        return "empty"
    top = st[0]
    if top.get("mine"):
        return "own"
    if top["kind"] == "ability":
        return "opp ability"
    return "opp creature spell" if "Creature" in top.get("types", "") else "opp noncreature spell"


def main():
    root = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/mtg-data/playmat-games")
    rows, auto, per_game = [], collections.Counter(), collections.Counter()
    games = 0
    for d in sorted(glob.glob(os.path.join(root, "*/*/"))):
        try:
            seats = json.load(open(d + "config.json"))["seats"]
        except (OSError, KeyError, ValueError):
            continue
        kinds = {s: v["kind"] for s, v in seats.items()}
        if sorted(kinds.values()) != ["claude", "human"]:
            continue
        seat = next(s for s, k in kinds.items() if k == "claude")
        f = d + f"seat-{seat}.jsonl"
        if not os.path.exists(f):
            continue
        superseded = set()
        if os.path.exists(d + "game0.jsonl"):
            for line in open(d + "game0.jsonl"):
                r = json.loads(line)
                if r.get("superseded") and r.get("seat") == seat:
                    superseded.add(r["idx"])
        games += 1
        for line in open(f):
            r = json.loads(line)
            if r["idx"] in superseded:
                continue
            if r.get("auto"):
                auto[str(r["auto"])] += 1
                continue
            g = r["obs"]["entries"][0]
            opts = r.get("options", [])
            choice = opts[r["choice"]] if 0 <= r.get("choice", -1) < len(opts) else {}
            is_pass = choice.get("action") in ("PASS", "DONE") or choice.get("label") in ("PASS", "DONE")
            nonpass = [o for o in opts if o.get("action") not in ("PASS", "DONE")]
            kind = {"PRIORITY": "priority", "ATTACK": "attack", "BLOCK": "block"}.get(r["kind"], "target" if "TARGET" in r["kind"] else "other")
            sk = stack_kind(r["obs"]["entries"]) if kind == "priority" else "-"
            row = dict(only=nonpass[0]["label"].split(" | ")[0] if len(nonpass) == 1 else None, game=d, secs=float(r.get("seconds") or 0), kind=kind, turn="own" if g.get("my_turn") else "opp",
                       step=g.get("step"), combat=g.get("step") in COMBAT, stack=sk, is_pass=is_pass,
                       nonpass=len(nonpass), life=g.get("my_life", 20))
            rows.append(row)
            per_game[d] += row["secs"]
    total = sum(r["secs"] for r in rows)

    def table(title, key):
        b = collections.defaultdict(list)
        for r in rows:
            k = key(r)
            if k is not None:
                b[k].append(r)
        print(f"\n{title}\n| bucket | n | secs | % time | median s | % pass |\n|---|---|---|---|---|---|")
        for k, rs in sorted(b.items(), key=lambda kv: -sum(x["secs"] for x in kv[1])):
            s = sum(x["secs"] for x in rs)
            print(f"| {k} | {len(rs)} | {s:.0f} | {100*s/total:.1f} | {statistics.median(x['secs'] for x in rs):.1f} | {100*sum(x['is_pass'] for x in rs)/len(rs):.0f} |")

    print(f"games {games}, Claude decisions {len(rows)}, Claude seconds {total:.0f} ({total/60:.1f} min), "
          f"per game median {statistics.median(per_game.values()):.0f}s, mean {total/max(1,games):.0f}s")
    print("auto-answered windows (no model call):", dict(auto))
    table("By kind", lambda r: r["kind"])
    table("Priority by turn / step group / stack", lambda r: (r["turn"], "combat" if r["combat"] else r["step"], r["stack"]) if r["kind"] == "priority" else None)
    table("Priority: pass or act, and non-pass options", lambda r: ("PASS" if r["is_pass"] else "act", min(r["nonpass"], 3)) if r["kind"] == "priority" else None)

    lone = collections.Counter(r["only"] for r in rows if r["kind"] == "priority" and r["is_pass"] and r["nonpass"] == 1)
    print("\nPASS with exactly one non-pass option, what that option was:", dict(lone.most_common(6)))

    def share(pred, label):
        rs = [r for r in rows if pred(r)]
        s = sum(r["secs"] for r in rs)
        print(f"- {label}: {len(rs)} decisions, {s:.0f}s ({100*s/total:.1f}% of Claude's time)")
    print("\nHighlights")
    share(lambda r: r["kind"] == "priority" and r["is_pass"] and r["nonpass"] == 0, "(a) PASS with no legal non-pass option")
    share(lambda r: r["kind"] == "priority" and r["is_pass"] and r["stack"] == "opp creature spell", "(b) PASS with an opponent creature spell on the stack")
    share(lambda r: r["kind"] == "priority" and r["is_pass"] and r["combat"], "(c) combat-window PASS")
    share(lambda r: r["turn"] == "own" and r["step"] in ("Precombat Main", "Postcombat Main"), "(d) Claude's own main phases (all kinds)")
    share(lambda r: r["kind"] == "priority" and r["is_pass"] and r["nonpass"] <= 1 and r["stack"] in ("empty", "own") and r["life"] > 8,
          "Haiku-gate candidates (PASS, <=1 non-pass option, no opponent object on the stack, life > 8)")


if __name__ == "__main__":
    main()
