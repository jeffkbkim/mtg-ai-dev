"""Per-game manifest for recorded Claude games: which games carry no known bug, so a training set can filter on it.

  python3 play/manifest.py [--root /mnt/project-files/claude-games] [--out <root>/manifest.jsonl] [run dir ...]

One line per finished game, combining three signals that every recording already carries:
- the seat version (config.json's code_commit) against the list of harness and XMage bugs fixed since, some of them
  only when the affected card appeared in the game;
- the engine's end-of-match counters in jvm.log: FALLBACK (XMage decided for the player: X values, mana colours,
  counter or damage splits), REJECTED (moves offered, then refused), LEAKS, UNMAPPED_*. One JVM serves every game of
  a part, so these attach to all games of the part;
- the reviewer's notes (play/review.py): "bugs" are suspected engine or harness problems (a note about a move
  offered then refused, a repeated prompt or a display glitch only counts as a caution, since the board did not
  change), "flags" are the player's own errors and are listed separately, since they are a quality filter rather
  than a bug.

Verdicts: "unusable" (a bug that corrupts every game on that seat version, or the game did not finish), "suspect"
(something decided or changed the board that the player never chose, or the reviewer reported a bug), "clean"
(none of the above). "cautions" lists weaker signals that may or may not have fired (a payer that could strand
colours, a buggy card that appeared, moves refused after being offered). Nothing is deleted or moved; the
manifest is a view, rebuilt from scratch on every run.
"""
import argparse, json, re, subprocess, sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (fix commit, level, card names or None, what was wrong before the fix). Order is the fix order on main.
FIXES = [
    ("7c43c35", "unusable", None, "every game started with an empty hand (fixed 7c43c35)"),
    ("6ed71e9", "unusable", None, "targets were chosen as the source's controller, a hidden-information leak (fixed 6ed71e9)"),
    ("a02cc66", "suspect", None, "XMage paid mana for the player and could tap the wrong lands (own payer since a02cc66)"),
    ("3e9b6d2", "caution", None, "the mana payer did not plan taps to keep the hand castable (fixed 3e9b6d2)"),
    ("b0674fe", "caution", None, "only one copy of duplicate permanents offered its activated ability (fixed b0674fe)"),
    ("38e42c2", "caution", "rooms", "a face-down Room kept its doors' abilities, XMage bug (patched 38e42c2)"),
    ("f3222cf", "caution", "rooms", "a refused Room door could be offered again in a loop (fixed f3222cf)"),
    ("da20d51", "caution", {"Valgavoth's Lair"}, "Valgavoth's Lair's colour was chosen by XMage's AI (fixed da20d51)"),
    ("da20d51", "caution", {"Veteran Survivor"}, "Veteran Survivor never got +3/+3 and hexproof, XMage bug (patched da20d51)"),
    ("da20d51", "caution", {"Overgrown Zealot"}, "the payer could spend Overgrown Zealot's mana on a cost it can't pay, so the move was refused (fixed da20d51)"),
]
LEVELS = {"clean": 0, "caution": 0, "suspect": 1, "unusable": 2}

# A reviewer's bug note is "suspect" when the board changed in a way the player never chose, and only a "caution"
# when nothing did (Jeff 2026-10-23): a move offered then refused or rolled back, a prompt repeated after DONE, a
# display or label glitch. Read in this order: a missing option or a changed board wins over the harmless phrasing.
MISSING = re.compile(r"not offered|never offered|no (?:\w+[- ])?(?:choice|decision|option)s? (?:was |were )?(?:offered|shown)|not among"
                     r"|only one .{0,30}(?:option|Equip)|missing option|offered no|never (?:got|produced)|(?:was )?never asked", re.I)
BOARD = re.compile(r"auto-?pay|automatic(?:ally)? (?:mana )?pay|mana payer|auto-?target|on the stack|resolved without|how to (?:assign|split)"
                   r"|damage|applied anyway|should have been|zone change|left the battlefield|put back|counter \(|reversed|put the counters"
                   r"|went onto|paid by tapping|was paid \(|distribute|double strike|still (?:shows|is|was|has)|stays", re.I)
HARMLESS = re.compile(r"refus|revert|roll(?:ed)? ?back|was undone|silently|cast failed|did nothing|not cast|dropped out|vanished"
                      r"|same .{0,60}prompt|identical .{0,60}prompt|re-?asked|came back|shown again|reappeared|label|'\?'|being_cast"
                      r"|clarity|(?:was|were|still|again) offered|offered (?:'|its|as|three)", re.I | re.S)


def reviewer_level(what):
    if MISSING.search(what) or BOARD.search(what):
        return "suspect"
    return "caution" if HARMLESS.search(what) else "suspect"


@lru_cache(None)
def fixed_in(commit, fix):
    """Whether the seat at `commit` includes `fix` (the fix is an ancestor of, or equal to, the commit)."""
    r = subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", fix, commit], capture_output=True)
    if r.returncode not in (0, 1):
        sys.exit(f"git cannot place commit {commit}: {r.stderr.decode().strip()} (run from a checkout with main's history)")
    return r.returncode == 0


def seat_counters(jvm_log):
    """Per seat: fallback kinds, refused moves, leaks and unmapped items from the end-of-match summary lines."""
    out = defaultdict(dict)
    text = jvm_log.read_text() if jvm_log.exists() else ""
    for seat, body in re.findall(r"^SEAT (\w) ASKED .*?FALLBACK \{([^}]*)\}", text, re.M):
        out[seat]["fallback"] = {k: int(v) for k, v in (kv.rsplit("=", 1) for kv in body.split(", ") if "=" in kv)}
    for seat, n, body in re.findall(r"^SEAT (\w) REJECTED (\d+) \[(.*)\]$", text, re.M):
        out[seat]["rejected"] = [s.strip() for s in body.split(", ") if s.strip()] if int(n) else []
    for seat, leaks, unseen in re.findall(r"^SEAT (\w) LEAKS \{(.*?)\} UNSEEN_REFS \{(.*?)\}$", text, re.M):
        out[seat]["leaks"] = leaks
    for seat, abil, choices in re.findall(r"^SEAT (\w) UNMAPPED_ABILITIES \{(.*?)\} UNMAPPED_CHOICES \{(.*?)\}$", text, re.M):
        out[seat]["unmapped"] = ", ".join(x for x in (abil, choices) if x)
    return out


def game_records(path):
    for line in path.read_text().splitlines():
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            pass


def one_game(part, cfg, end, counters, part_games, root):
    g = end["game"]
    gf = part / f"game{g}.jsonl"
    recs = list(game_records(gf)) if gf.exists() else []
    cards = {e["name"] for r in recs for e in r.get("obs", {}).get("entries", []) if e.get("kind") == "card"}
    rooms = {c for c in cards if " // " in c}
    commit = cfg.get("code_commit", "")
    row = {"run": run_name(part, root), "part": part.name, "game": g, "file": str(gf), "code_commit": commit[:7],
           "a": end.get("a", cfg.get("a")), "b": end.get("b", cfg.get("b")),
           "deck_a": Path(cfg.get("deck_a", "")).name, "deck_b": Path(cfg.get("deck_b", "")).name,
           "first": end.get("first"), "winner": end.get("winner"), "turns": end.get("turns"),
           "decisions": {s: sum(1 for r in recs if r.get("seat") == s and not r.get("auto")) for s in "AB"},
           "part_games": part_games, "reviewed": all((part / f"game{g}.review-{s}.json").exists() for s in "AB"),
           "reasons": [], "cautions": [], "flags": []}
    # seat version
    for fix, level, when, what in FIXES:
        if fixed_in(commit, fix):
            continue
        if when == "rooms":
            hit = sorted(rooms)
        elif when:
            hit = sorted(cards & when)
        else:
            hit = None
        if when and not hit:
            continue
        note = {"source": "seat_version", "what": what + (f"; in this game: {', '.join(hit)}" if hit else "")}
        (row["reasons"] if level in ("suspect", "unusable") else row["cautions"]).append({**note, "level": level})
    # engine counters, shared by the games of the part
    scope = "" if part_games == 1 else f" (counted over the part's {part_games} games)"
    for seat in "AB":
        c = counters.get(seat, {})
        if c.get("fallback"):
            kinds = ", ".join(f"{k} x{v}" for k, v in sorted(c["fallback"].items()))
            row["reasons"].append({"source": "engine", "seat": seat, "level": "suspect",
                                   "what": f"XMage decided for seat {seat}: {kinds}{scope}"})
        if c.get("leaks"):
            row["reasons"].append({"source": "engine", "seat": seat, "level": "unusable", "what": f"hidden-information leak: {c['leaks']}{scope}"})
        if c.get("rejected"):
            row["cautions"].append({"source": "engine", "seat": seat, "level": "caution",
                                    "what": f"{len(c['rejected'])} moves offered then refused by the engine{scope}: " + "; ".join(c["rejected"][:6])})
        if c.get("unmapped"):
            row["cautions"].append({"source": "engine", "seat": seat, "level": "caution", "what": f"unmapped abilities or choices{scope}: {c['unmapped']}"})
    # reviewer
    for seat in "AB":
        rf = part / f"game{g}.review-{seat}.json"
        if not rf.exists():
            continue
        rev = json.loads(rf.read_text())
        for b in rev.get("bugs", []):
            level = reviewer_level(b.get("what", ""))
            (row["reasons"] if level == "suspect" else row["cautions"]).append(
                {"source": "reviewer", "seat": seat, "idx": b.get("idx"), "level": level, "what": b.get("what", "")})
        for f in rev.get("flags", []):
            row["flags"].append({"seat": seat, "idx": f.get("idx"), "severity": f.get("severity"), "category": f.get("category"), "what": f.get("what", "")})
    row["verdict"] = max((r["level"] for r in row["reasons"]), key=LEVELS.get, default="clean")
    return row


def run_name(part, root):
    """The run a part belongs to, relative to the recordings root: parts are the partNN directories of a batch."""
    run = part.parent if re.fullmatch(r"part\d+", part.name) else part
    try:
        return str(run.resolve().relative_to(root.resolve()))
    except ValueError:
        return run.name


def parts_under(paths):
    for p in paths:
        p = Path(p)
        if (p / "config.json").exists():
            yield p
        else:
            yield from sorted(q.parent for q in p.rglob("config.json"))


def build(paths, root):
    rows = []
    for part in parts_under(paths):
        cfg = json.loads((part / "config.json").read_text())
        ends = [r for r in (game_records(part / "games.jsonl") if (part / "games.jsonl").exists() else []) if r.get("type") == "game_end"]
        counters = seat_counters(part / "jvm.log")
        finished = {e["game"] for e in ends}
        for e in ends:
            rows.append(one_game(part, cfg, e, counters, len(ends), root))
        for gf in sorted(part.glob("game*.jsonl")):
            if not re.fullmatch(r"game\d+", gf.stem) or int(gf.stem[4:]) in finished:
                continue
            g = int(gf.stem[4:])
            rows.append({"run": run_name(part, root), "part": part.name, "game": g, "file": str(gf), "code_commit": cfg.get("code_commit", "")[:7],
                         "verdict": "unusable", "reviewed": False, "flags": [], "cautions": [],
                         "reasons": [{"source": "run", "level": "unusable", "what": "the game did not finish (no game_end record)"}]})
    return rows


def report(rows):
    by = defaultdict(Counter)
    for r in rows:
        c = by[r["run"]]
        c["games"] += 1; c[r["verdict"]] += 1
        c["reviewed"] += r["reviewed"]
        c["clean+reviewed"] += r["verdict"] == "clean" and r["reviewed"]
        c["clean+reviewed+no flags"] += r["verdict"] == "clean" and r["reviewed"] and not r["flags"]
        c["cautions"] += bool(r["cautions"])
    cols = ("games", "unusable", "suspect", "clean", "reviewed", "clean+reviewed", "clean+reviewed+no flags")
    width = max(len(k) for k in by) + 2
    print("run".ljust(width) + "".join(c.rjust(len(c) + 2) for c in cols))
    tot = Counter()
    for run, c in by.items():
        tot.update({k: c[k] for k in cols})
        print(run.ljust(width) + "".join(str(c[k]).rjust(len(k) + 2) for k in cols))
    print("total".ljust(width) + "".join(str(tot[k]).rjust(len(k) + 2) for k in cols))
    why = Counter()
    for r in rows:
        for x in r["reasons"]:
            why[(x["source"], x["what"].split(":")[0][:60])] += 1
    print("\nmost common reasons:")
    for (src, what), n in why.most_common(12):
        print(f"  {n:4d}  {src}: {what}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--root", default="/mnt/project-files/claude-games")
    ap.add_argument("--out", help="manifest file (default <root>/manifest.jsonl)")
    args = ap.parse_args()
    rows = build(args.paths or [args.root], Path(args.root).resolve())
    out = Path(args.out or Path(args.root) / "manifest.jsonl")
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"{len(rows)} games -> {out}\n")
    report(rows)
