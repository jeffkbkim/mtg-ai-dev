"""Flag clear blunders in recorded Claude games, one review per seat per game, so they can be filtered from training data.

  python3 play/review.py <run dir or game*.jsonl> ... [--model claude-opus-5-5] [--effort high] [--parallel 4] [--fraction 0.5]
  python3 play/review.py <run dir> ... --summary     # counts only, no new reviews

A reviewer (headless `claude -p`, no tools) reads one seat's game exactly as that seat saw it: each asked decision
with the state (when it changed), options, the pick and the player's reason and plan. Auto-passed windows are
collapsed. It returns flags ("blunder" or "mistake") judged only on what the seat could see at the time, plus anything
that looks like an engine or harness bug. Nothing is deleted: flags go to <game>.review-<seat>.json next to the game,
and filtering is a choice made when building a training set. Existing reviews are kept (delete one to redo it).
"""
import argparse, hashlib, json, os, re, subprocess, sys, tempfile, time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from players import read_deck
from render import card_text, clean, load_card_text, names_in, option_label, render

ROOT = Path(__file__).resolve().parent.parent

REVIEW_RULES = """You review one player's decisions from a finished game of Magic: The Gathering, Duskmourn (DSK) Limited, 40-card
decks, played by an AI through the XMage engine. You see the game exactly as this player saw it: each decision shows
the state (only when it changed since the player's previous decision), the numbered options, the option picked and the
player's own reason (and its plan, if it kept one). Mana is paid automatically, and decisions with only one legal
option, or windows the player chose to pass through, are not shown. Turn numbers count both players' turns.

Your job: find this player's clear errors, so they can be left out of training data. Flag a decision only when a
competent Limited player, looking at the same information at that moment, would see that another option was clearly
better.

Severity:
- "blunder": a clear error with a real cost. For example: missing lethal, or leaving yourself dead on board when it was
  avoidable; an attack or block that loses a creature for nothing; spending removal or a key card on a minor target
  while a much bigger threat stands; skipping a land drop or an obviously good play for no reason.
- "mistake": clearly worse than an available option, with a smaller cost.

Category, the main reason the decision was wrong:
- "rules": a rules, timing or card-text misread (e.g. thinking a creature or land untaps before the opponent's turn,
  that mana spent now is available on their turn, or what a card does);
- "combat_math": combat or lethal arithmetic (a block or attack that loses on the numbers, missing lethal, miscounting
  damage that gets through);
- "crack_back": an attack or tap that leaves too little defence against the opponent's swing back;
- "hidden_info": ignoring a clearly signalled risk from cards the player can't see (open mana for a likely trick,
  the opponent passing with mana up);
- "other": anything else.

Do not flag:
- judgment calls where reasonable players differ, or where you are unsure;
- decisions that only look bad because of information the player could not see at that moment (the opponent's hand,
  the top of a library, a trick that was not signalled). Later parts of the transcript show what happened: use them to
  understand consequences, never to fault a decision that was reasonable when it was made;
- harmless order or sequencing differences with no cost.
Most decisions in a game are fine; flagging none or a few is normal.

Separately, report anything that looks like an engine or harness bug rather than a player error: an option that should
have been offered and wasn't, a choice that didn't do what its label said, a state that contradicts the rules or the
card text, or information this player should not have been able to see.

Reply with one JSON object and nothing else:
{"flags": [{"idx": <decision number after '#'>, "severity": "blunder" or "mistake", "category": "rules", "combat_math", "crack_back", "hidden_info" or "other", "what": "<what the player did and why it was clearly wrong, from what was visible then>", "better": "<the better option>"}], "bugs": [{"idx": <decision number>, "what": "<what looks wrong>"}]}"""

SYSTEM_SHA = hashlib.sha256(REVIEW_RULES.encode()).hexdigest()[:12]


def seat_transcript(records, seat, deck_path, texts, result_line):
    """The seat's own view of the game as text, and the idx values of the decisions it was asked."""
    lines, names, asked, last_state, auto = [], set(), set(), None, 0
    for r in records:
        if r.get("seat") != seat:
            continue
        names |= names_in(r["obs"])
        if r.get("auto"):
            auto += 1
            continue
        if auto:
            lines.append(f"[{auto} window(s) passed automatically]\n")
            auto = 0
        asked.add(r["idx"])
        state, _, decision = render(r).partition("\nDecision: ")
        g = r["obs"]["entries"][0]
        lines.append(f"=== #{r['idx']} | turn {g['turn']} {g['step']} | life me {g['my_life']} opp {g['opp_life']}")
        lines.append(state if state != last_state else "(state unchanged)")
        last_state = state
        lines.append("Decision: " + decision)
        lines.append(f">>> picked {r['choice']}: {option_label(r['options'][r['choice']], r['obs']['entries'])} | reason: {r.get('reason', '')}")
        if r.get("plan"):
            lines.append(">>> plan: " + "; ".join(f"{k}: {v}" for k, v in r["plan"].items()))
        lines.append("")
    deck = read_deck(deck_path)
    names |= {n for _, n in deck}
    head = ["This player's deck (the opponent's deck was unknown to them):"]
    head += [f"{n}x {name}" for n, name in deck]
    head += ["", "Rules text of the cards that appear (as XMage implements them):"]
    head += [card_text(texts[n]) for n in sorted(names) if n in texts]
    head += ["", f"Result: {result_line}", "", "Transcript:"]
    return "\n".join(head + lines), asked


def ask_reviewer(text, model, effort, timeout_s):
    work = tempfile.mkdtemp(prefix="claude-review-")
    Path(work, "system.txt").write_text(REVIEW_RULES)
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID")}
    env["CLAUDE_EFFORT"] = effort
    env["DISABLE_PROMPT_CACHING"] = "1"  # one-shot call: a cache write would cost more than plain input and never be read
    t0 = time.time()
    p = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--model", model, "--effort", effort,
         "--system-prompt-file", "system.txt", "--tools", "", "--strict-mcp-config", "--setting-sources", "",
         "--no-session-persistence"],
        input=text, cwd=work, env=env, capture_output=True, text=True, timeout=timeout_s)
    out = json.loads(p.stdout)
    if out.get("is_error"):
        raise RuntimeError(f"reviewer error: {out.get('result')}")
    return out.get("result") or "", out.get("total_cost_usd") or 0.0, out.get("usage", {}), time.time() - t0


def parse(reply):
    """The JSON object in the reply (it may be wrapped in a code fence)."""
    i, j = reply.find("{"), reply.rfind("}")
    if i < 0 or j < i:
        return None
    try:
        return json.loads(reply[i:j + 1])
    except json.JSONDecodeError:
        return None


def review_one(game_file, seat, args, texts):
    out_path = game_file.with_name(f"{game_file.stem}.review-{seat}.json")
    if out_path.exists():
        return out_path, "kept"
    records = [json.loads(l) for l in open(game_file) if l.strip()]
    mine = [r for r in records if r.get("seat") == seat]
    if not mine:
        return out_path, "no decisions"
    config = json.loads((game_file.parent / "config.json").read_text())
    deck = ROOT / config[f"deck_{seat.lower()}"]
    game_no = mine[0]["game"]
    result_line = "unknown (game did not finish)"
    gpath = game_file.parent / "games.jsonl"
    if gpath.exists():
        for l in open(gpath):
            g = json.loads(l)
            if g.get("game") == game_no:
                won = "won" if g.get("winner") == seat else ("lost" if g.get("winner") else "no winner")
                result_line = f"this player {won}; the game ended on turn {g.get('turns')}"
    text, asked = seat_transcript(records, seat, deck, texts, result_line)
    reply = parsed = None
    cost = secs = 0.0
    usage = {}
    for attempt in range(2):  # one retry on an unreadable reply or a failed call
        try:
            reply, c, usage, s = ask_reviewer(text, args.model, args.effort, args.timeout)
            cost += c; secs += s
        except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            reply = f"[error] {e}"
            continue
        parsed = parse(reply)
        if isinstance(parsed, dict):
            break
    if not isinstance(parsed, dict):
        return out_path, f"failed: {reply[:200] if reply else ''}"
    flags = [f for f in parsed.get("flags", []) if isinstance(f, dict)]
    for f in flags:
        f["idx_valid"] = f.get("idx") in asked
    review = {"game_file": str(game_file), "game": game_no, "seat": seat, "player": mine[0]["player"],
              "reviewer": {"model": args.model, "effort": args.effort, "rules_sha": SYSTEM_SHA},
              "asked": len(asked), "flags": flags, "bugs": parsed.get("bugs", []),
              "cost_usd": round(cost, 4), "seconds": round(secs, 1), "usage": usage, "transcript_chars": len(text)}
    out_path.write_text(json.dumps(review, indent=1))
    return out_path, f"{len(flags)} flags, {len(review['bugs'])} bugs, ${cost:.2f}"


def game_files(paths):
    for p in map(Path, paths):
        if p.is_dir():
            yield from sorted(p.rglob("game[0-9]*.jsonl"))
        elif re.fullmatch(r"game\d+\.jsonl", p.name):
            yield p


CATEGORIES = ("rules", "combat_math", "crack_back", "hidden_info", "other")


def summary(paths):
    per = defaultdict(Counter)
    for gf in game_files(paths):
        for rf in gf.parent.glob(f"{gf.stem}.review-*.json"):
            r = json.loads(rf.read_text())
            c = per[r["player"]]
            c["reviews"] += 1; c["asked"] += r["asked"]; c["bugs"] += len(r["bugs"]); c["cost_cents"] += round(100 * r["cost_usd"])
            for f in r["flags"]:
                c[f.get("severity", "?")] += 1
                c["cat:" + (f.get("category") if f.get("category") in CATEGORIES else "uncategorized")] += 1
    for player, c in sorted(per.items()):
        n = max(c["asked"], 1)
        print(f"{player}: {c['reviews']} seat-games, {c['asked']} decisions; blunders {c['blunder']} "
              f"({100 * c['blunder'] / n:.1f}%), mistakes {c['mistake']} ({100 * c['mistake'] / n:.1f}%), "
              f"suspected bugs {c['bugs']}; review cost ${c['cost_cents'] / 100 / max(c['reviews'], 1):.2f} per seat-game")
        cats = [(k[4:], v) for k, v in c.items() if k.startswith("cat:") and v]
        if cats:
            print("  flags per 1,000 decisions: " + ", ".join(f"{k} {1000 * v / n:.1f}" for k, v in sorted(cats)))


def picked(game_file, fraction):
    """Whether this game is in the reviewed sample: a stable hash of its path, so reruns pick the same games."""
    return int(hashlib.sha256(str(Path(game_file).resolve()).encode()).hexdigest()[:8], 16) < fraction * 2 ** 32


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--fraction", type=float, default=0.5,
                    help="review this share of the games (both seats), picked by a hash of the path (Jeff 2026-10-23: half)")
    args = ap.parse_args()
    if not args.summary:
        texts = load_card_text()
        jobs = [(gf, seat) for gf in game_files(args.paths) if picked(gf, args.fraction) for seat in ("A", "B")]
        with ThreadPoolExecutor(args.parallel) as ex:
            for path, status in ex.map(lambda j: review_one(j[0], j[1], args, texts), jobs):
                print(f"{path}: {status}", flush=True)
    summary(args.paths)
