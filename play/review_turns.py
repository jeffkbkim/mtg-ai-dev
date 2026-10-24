"""Review recorded Playmat games turn by turn, both seats, with race math first: a stronger pass than play/review.py.

  python3 play/review_turns.py <game dir> ... [--seats A,B] [--model claude-opus-5-5] [--effort high] [--parallel 5]
                               [--budget 30] [--redo]
  python3 play/review_turns.py <game dir> ... --summary      # print the stored reviews, no new calls

One headless `claude -p` call (no tools) per turn of the reviewed seat. A "turn" is the seat's own turn plus the
opponent's next turn (blocks and instant-speed plays there answer the seat's own attacks and taps); mulligans and any
decisions before the seat's first turn join its first turn. Each call gets, as that seat saw it: the seat's deck with
card text (in the system prompt, so it is cached across the seat's calls), the text of other cards it can see, the
state at the start of the turn, a compact public game log of the turns before, and every decision it was asked that
turn with the options and the pick. The player's own reasons and plans are NOT shown (no anchoring); they are added to
the stored flags afterwards. The reply starts with race math (both clocks, who is the beatdown, hands), then judges
the turn's decisions (blunder / mistake / questionable, with a category and the better line) and lists suspected
engine, UI or recording bugs. Human seats also get a short plain-words coaching note.

Replies are cached by prompt hash under ~/mtg-data/reviews-cache/turns/, so reruns don't pay again. Results go to
<game dir>/game0.review-turns-<seat>.json. Only finished games (games.jsonl) are reviewed; smoke tests (Smoketest,
tester*) and games shorter than --min-turns are skipped and reported. play/review.py is unchanged.
"""
import argparse, hashlib, json, os, re, subprocess, sys, tempfile, threading, time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from players import read_deck
from render import card_text, events, load_card_text, names_in, option_label, render
from review import parse

CACHE = Path.home() / "mtg-data" / "reviews-cache" / "turns"

RULES = """You review one player's decisions during ONE turn cycle of a finished game of Magic: The Gathering, Duskmourn
(DSK) Limited, 40-card decks, 20 life, played through the XMage engine. The turn cycle is the player's own turn plus
the opponent's next turn (blocks and responses there answer the player's own attacks and taps). Turn numbers count
both players' turns. You see exactly what this player could see: its own deck and hand, the battlefield, graveyards,
exile, revealed cards, a public log of earlier turns, and each decision it was asked with the state, the numbered
options and the option picked. Mana is paid automatically; decisions with one legal option and windows passed
automatically are not shown. Attacks and blocks are declared one at a time ("X attacks", then DONE); the order does
not matter, only the final set. The player's reasons are deliberately not shown: judge the play, not the explanation.

Work in this order.

1. Race math, before judging anything. From the state at the start of the turn: how many turns each side needs to kill
the other with the creatures on board (count evasion such as flying and menace, the blockers the other side really
has for it, drains and life loss from triggers, repeatable pumps, counters that grow), how many cards each side holds,
untapped mana, and who should be the beatdown (attacking, racing) and who the control (blocking, trading, preserving
life and chump blockers). Then note how the turn's plays change these clocks.

2. Judge every decision of the turn against that picture, using only what this player could see at that moment.
Later decisions show what happened next: use them to understand consequences, never to fault a choice that was
reasonable when made. Things a strong Limited player checks:
- A losing racer keeps its blockers, especially the few that can block the opponent's evasive threats, unless the
  attack changes the clock enough to win first. Count the crack-back before every attack: which attackers stay tapped
  through the opponent's turn and what then gets through.
- Combat math: blocks and attacks that lose a creature for nothing, missed lethal, damage that gets through, first
  strike, deathtouch, menace, trample, pumps the player already has on board.
- Auras, counters and equipment go on a host that will keep them. A creature already neutralised by an opposing
  effect (a Pacifism-style aura, a lock that the opponent can turn into removal), or exposed to the opponent's
  non-targeting answers (shuffle, sacrifice, exile or bounce effects that do not target, -X/-X to all, edicts), is a
  poor host: ward, hexproof and protection do not stop non-targeting effects. Read the opponent's visible permanents'
  activated and triggered abilities.
- Signalled tricks: open mana on the opponent's side, cards in hand, a creature that can flip face up.
- Sequencing (land before spells, removal before combat or after blocks, holding instants), mana and colours,
  mulligans, missed land drops, wasted removal on a minor target while a bigger threat stands.

Severity:
- "blunder": a clear error with a real cost (loses a creature or a lot of life for nothing, misses lethal, walks into
  a loss that was avoidable, throws away a key card or the race);
- "mistake": clearly worse than an available option, with a smaller or less certain cost;
- "questionable": probably worse, or you are unsure; use it freely when a line looks off but you can't prove it.
Most decisions are fine; list only decisions you would flag (questionable or worse).

Category, the main reason: "race_math", "combat_math", "crack_back", "non_targeting_answer",
"aura_or_protection_host", "hidden_info/tricks", "sequencing", "mana/colors", "mulligan" or "other".

Separately report anything that looks like an engine, UI or recording bug rather than a player error: an option that
should have been offered and wasn't, a choice that did not do what its label said, a state that contradicts the rules
or the card text, a recorded pick that looks impossible or inconsistent, or information this player should not see.
{SEAT_NOTE}
Reply with one JSON object and nothing else, in this key order:
{"race": {"my_clock": "<turns until this player kills the opponent, and why>", "opp_clock": "<turns until the
opponent kills this player, and why>", "beatdown": "me", "opponent" or "unclear", "hands": "<cards in hand, both
sides; open mana>", "summary": "<one or two sentences: what this turn had to achieve>"},
 "decisions": [{"idx": <decision number after '#'>, "severity": "blunder", "mistake" or "questionable",
 "category": "<one of the categories>", "what": "<what the player did and why it was worse, from what was visible
 then>", "better": "<the better line>"}],
 "bugs": [{"idx": <decision number or null>, "what": "<what looks wrong>"}]{COACH_KEY}}"""

CLAUDE_NOTE = """
This player is an AI. Be strict: the goal is to find its misplays so they can be fixed."""

HUMAN_NOTE = """
This player is a person learning Limited, playing in a web client (Playmat). Some of its recorded decisions were
rebuilt from what it declared in the browser ("mapping": exact, inferred, unmapped; a block XMage refused shows as a
refused line). Coach: find the plays that cost the most and say the better line in plain, friendly words, without
jargon where a simple word works."""

COACH_KEY = ',\n "coaching": "<one to three plain sentences: the main lesson of this turn, or \\"fine turn\\">"'


def system_text(deck, texts, human):
    rules = RULES.replace("{SEAT_NOTE}", HUMAN_NOTE if human else CLAUDE_NOTE).replace("{COACH_KEY}", COACH_KEY if human else "")
    lines = [rules, "", "This player's deck (40 cards; the opponent's deck is unknown to it):"]
    lines += [f"{n}x {name}" for n, name in deck]
    lines += ["", "Rules text of this player's cards (as XMage implements them):"]
    lines += [card_text(texts[name]) for _, name in deck if name in texts]
    return "\n".join(lines)


def turn_of(r):
    g = r["obs"]["entries"][0]
    return g["turn"] if g["my_turn"] else g["turn"] - 1  # the opponent's turn joins the seat's turn before it


def units(records, seat):
    """{unit turn: [records of this seat]} in order; anything before the seat's first own turn joins that turn."""
    mine = [r for r in records if r.get("seat") == seat]
    own = sorted({r["obs"]["entries"][0]["turn"] for r in mine if r["obs"]["entries"][0]["my_turn"]})
    first = own[0] if own else 1
    out = defaultdict(list)
    for r in mine:
        out[max(turn_of(r), first)].append(r)
    return dict(sorted(out.items()))


NOISE = re.compile(r"draws a card|skips Draw step|from hand onto the Battlefield|from stack onto the Battlefield"
                   r"|library is shuffled|^Match score|draws seven cards")


def compact_log(log, before_turn, full_turns=6):
    """The public log before this turn: the last full_turns turns in full, earlier turns as their TURN lines only."""
    out, last = [], None
    for l in log:
        if l["turn"] >= before_turn:
            break
        if l["turn"] < before_turn - full_turns and not l["text"].startswith("TURN"):
            continue
        t = re.sub(r" ?\[[0-9a-f]{3}\]", "", l["text"]).replace("&mdash;", "-")
        if NOISE.search(t) or t == last:
            continue
        last = t
        if l["type"] == "STATUS" and not t.startswith("TURN"):
            continue
        out.append(("" if t.startswith("TURN") else "  ") + (t if len(t) <= 170 else t[:167] + "..."))
    return out


def state_delta(old, new):
    """The new state, or only its changed lines when most of it is unchanged (keeps long combats short)."""
    if new == old:
        return "(state unchanged)"
    o, n = old.split("\n"), new.split("\n")  # lines compared with their [entry] numbers: options refer to them
    changed = [l for l in n[1:] if l not in set(o)]
    gone = len(set(o[1:]) - set(n[1:]))
    if len(changed) > len(n) // 3:
        return new
    return "\n".join([n[0], "(other lines as before; changed or new lines:)"] + changed
                     + ([f"({gone} earlier line(s) no longer apply)"] if gone else []))


def human_extra(r):
    bits = []
    if r.get("mapping") and r["mapping"] != "exact":
        bits.append(f"mapping {r['mapping']}")
    if r.get("engine_adjusted"):
        bits.append(f"engine adjusted the declared blocks (declared: {r.get('declared')})")
    if r.get("choice", 0) < 0:
        bits.append(f"browser answer: {json.dumps(r.get('ui'))[:300]}")
    return (" | " + "; ".join(bits)) if bits else ""


def unit_text(recs, all_mine, log, texts, deck_names):
    first = recs[0]
    g0 = first["obs"]["entries"][0]
    seen = set()
    for r in recs:
        seen |= names_in(r["obs"])
    other = sorted(n for n in seen - deck_names if n in texts)
    lines = []
    if other:
        lines += ["Text of other cards this player can see (opponent's, tokens, revealed):"]
        lines += ["  " + card_text(texts[n]) for n in other]
        lines.append("")
    hist = compact_log(log, g0["turn"])
    lines += ["Public game log of the earlier turns:"] + (hist or ["(none)"]) + [""]
    lines += [f"State at the start of this turn cycle (turn {g0['turn']}, {g0['step']}):",
              render(first).partition("\nDecision: ")[0], ""]
    lines.append("Decisions this turn cycle:")
    pos = {id(r): i for i, r in enumerate(all_mine)}
    last_state, asked = render(first).partition("\nDecision: ")[0], []
    for r in recs:
        if r.get("auto"):
            continue
        asked.append(r["idx"])
        i = pos[id(r)]
        ev = events(all_mine[i - 1]["obs"], r["obs"]) if i else []
        state, _, decision = render(r).partition("\nDecision: ")
        g = r["obs"]["entries"][0]
        lines.append(f"=== #{r['idx']} | turn {g['turn']} {g['step']}, {'own' if g['my_turn'] else 'opponent'} turn"
                     f" | life me {g['my_life']} opp {g['opp_life']}")
        if ev:
            lines.append("Since the previous decision: " + "; ".join(ev))
        lines.append(state_delta(last_state, state))
        last_state = state
        lines.append("Decision: " + decision)
        pick = option_label(r["options"][r["choice"]], r["obs"]["entries"]) if r.get("choice", -1) >= 0 else "(none recorded)"
        lines.append(f">>> picked {r.get('choice')}: {pick}{human_extra(r)}")
        lines.append("")
    return "\n".join(lines), asked


SPENT = [0.0]
LOCK = threading.Lock()


def ask(system, text, model, effort, timeout_s, budget):
    key = hashlib.sha256(f"{model}|{effort}|{system}|{text}".encode()).hexdigest()[:24]
    cpath = CACHE / f"{key}.json"
    if cpath.exists():
        c = json.loads(cpath.read_text())
        return c["reply"], 0.0, c["cost_usd"], c.get("usage", {}), True
    with LOCK:
        if SPENT[0] >= budget:
            raise RuntimeError("budget reached")
    work = tempfile.mkdtemp(prefix="claude-review-turns-")
    Path(work, "system.txt").write_text(system)
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID")}
    env["PATH"] = f"{Path.home()}/.local/bin:" + env.get("PATH", "")
    env["CLAUDE_EFFORT"] = effort
    p = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--model", model, "--effort", effort,
         "--system-prompt-file", "system.txt", "--tools", "", "--strict-mcp-config", "--setting-sources", "",
         "--no-session-persistence"],
        input=text, cwd=work, env=env, capture_output=True, text=True, timeout=timeout_s)
    out = json.loads(p.stdout)
    cost = out.get("total_cost_usd") or 0.0
    with LOCK:
        SPENT[0] += cost
    if out.get("is_error"):
        raise RuntimeError(f"reviewer error: {out.get('result')}")
    reply = out.get("result") or ""
    if isinstance(parse(reply), dict):
        CACHE.mkdir(parents=True, exist_ok=True)
        cpath.write_text(json.dumps({"reply": reply, "cost_usd": cost, "usage": out.get("usage", {})}))
    return reply, cost, cost, out.get("usage", {}), False


def seat_info(config, seat, recs):
    s = config.get("seats", {}).get(seat, {})
    player = s.get("player") or config.get(seat.lower()) or recs[0].get("player", "")
    info = {"name": s.get("name"), "kind": s.get("kind"), "player": player}
    if s.get("kind") == "claude":
        parts = player.split(":")
        info["model"] = s.get("model") or next((r.get("model") for r in recs if r.get("model")), parts[1] if len(parts) > 1 else None)
        info["effort"] = s.get("effort") or next((r.get("effort") for r in recs if r.get("effort")), parts[2] if len(parts) > 2 else None)
    return info


def review_seat(gdir, seat, args, texts):
    out_path = gdir / f"game0.review-turns-{seat}.json"
    if out_path.exists() and not args.redo:
        return out_path, "kept", 0.0
    config = json.loads((gdir / "config.json").read_text())
    # what a take-back undid (engine/playmat/README.md) is left out: decisions marked superseded, and the game log's
    # lines from the same undone stretch (before a rollback to turn N, from turn N on; or from the turn a later game
    # carried this one on from)
    rbs, sb = config.get("rollbacks") or [], config.get("superseded_by")
    undone = lambda o: (any(o.get("ts", 0) < rb["ts"] and o.get("turn", 0) >= rb["to_turn"] for rb in rbs)
                        or bool(sb) and o.get("turn", 0) >= sb["from_turn"])
    records = [r for r in (json.loads(l) for l in open(gdir / "game0.jsonl") if l.strip()) if not r.get("superseded")]
    log = [o for o in (json.loads(l) for l in open(gdir / "game_log.jsonl") if l.strip())
           if not undone(o)] if (gdir / "game_log.jsonl").exists() else []
    mine = [r for r in records if r.get("seat") == seat]
    if not mine:
        return out_path, "no decisions", 0.0
    info = seat_info(config, seat, mine)
    human = info["kind"] == "human"
    deck = read_deck(gdir / f"deck-{seat}.dck")
    system = system_text(deck, texts, human)
    deck_names = {n for _, n in deck}
    turns, paid, total = [], 0.0, 0.0
    for t, recs in units(records, seat).items():
        text, asked = unit_text(recs, mine, log, texts, deck_names)
        if not asked:
            continue
        reply = parsed = None
        err = None
        for _ in range(2):
            try:
                reply, c_paid, c_total, usage, cached = ask(system, text, args.model, args.effort, args.timeout, args.budget)
                paid += c_paid; total += c_total
            except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
                err = str(e)
                if "budget" in err:
                    break
                continue
            parsed = parse(reply)
            if isinstance(parsed, dict):
                break
        if not isinstance(parsed, dict):
            turns.append({"turn": t, "asked": asked, "error": err or (reply or "")[:300]})
            continue
        by_idx = {r["idx"]: r for r in recs}
        flags = [f for f in parsed.get("decisions", []) if isinstance(f, dict)]
        for f in flags:
            r = by_idx.get(f.get("idx"))
            f["idx_valid"] = f.get("idx") in asked
            if r is not None and r.get("reason"):
                f["player_reason"] = r["reason"]  # added after the judgment, for the reader
        turns.append({"turn": t, "asked": asked, "race": parsed.get("race"), "flags": flags,
                      "bugs": parsed.get("bugs", []), "coaching": parsed.get("coaching"), "prompt_chars": len(text)})
    review = {"game_dir": str(gdir), "seat": seat, **info,
              "reviewer": {"model": args.model, "effort": args.effort,
                           "rules_sha": hashlib.sha256(RULES.encode()).hexdigest()[:12]},
              "turns": turns, "cost_usd": round(total, 4), "cost_paid_this_run": round(paid, 4)}
    if any("error" in t for t in turns):
        review["incomplete"] = True
    out_path.write_text(json.dumps(review, indent=1))
    n = Counter(f.get("severity") for t in turns for f in t.get("flags", []))
    return out_path, f"{len(turns)} turns, {dict(n)}, {sum(len(t.get('bugs', [])) for t in turns)} bugs, ${paid:.2f} paid", paid


def eligible(gdir, min_turns):
    """(ok, why) for a game folder."""
    if not (gdir / "games.jsonl").exists() or not (gdir / "game0.jsonl").exists():
        return False, "not finished"
    config = json.loads((gdir / "config.json").read_text())
    seats = config.get("seats", {})
    names = [s.get("name", "") for s in seats.values()]
    if not any(s.get("kind") == "human" for s in seats.values()):
        return False, "no human seat"
    if any(n == "Smoketest" or n.lower().startswith("tester") for n in names):
        return False, "smoke test"
    g = json.loads(open(gdir / "games.jsonl").readline())
    if g.get("turns", 0) < min_turns:
        return False, f"only {g.get('turns')} turns"
    return True, ""


def game_dirs(paths):
    for p in map(Path, paths):
        if (p / "config.json").exists():
            yield p
        elif p.is_dir():
            yield from sorted(d.parent for d in p.rglob("config.json"))


def summary(paths):
    for gdir in game_dirs(paths):
        for rf in sorted(gdir.glob("game0.review-turns-*.json")):
            r = json.loads(rf.read_text())
            n = Counter(f.get("severity") for t in r["turns"] for f in t.get("flags", []))
            print(f"{gdir.name[:8]} {r['seat']} {r['player']}: {len(r['turns'])} turns, {dict(n)}, ${r['cost_usd']:.2f}")
            for t in r["turns"]:
                for f in t.get("flags", []):
                    print(f"  t{t['turn']} #{f.get('idx')} {f.get('severity')} {f.get('category')}: {f.get('what')}")
                for b in t.get("bugs", []):
                    print(f"  t{t['turn']} BUG #{b.get('idx')}: {b.get('what')}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--seats", default="A,B")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--parallel", type=int, default=5)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--budget", type=float, default=30.0, help="stop making new calls once this run has paid this much")
    ap.add_argument("--min-turns", type=int, default=4)
    ap.add_argument("--redo", action="store_true", help="rebuild review files (cached replies are still reused)")
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()
    if not args.summary:
        texts = load_card_text()
        jobs = []
        for gdir in game_dirs(args.paths):
            ok, why = eligible(gdir, args.min_turns)
            if not ok:
                print(f"{gdir}: skipped ({why})", flush=True)
                continue
            jobs += [(gdir, s) for s in args.seats.split(",")]
        with ThreadPoolExecutor(args.parallel) as ex:  # one seat-game per worker: its turns run in order, sharing the cache
            for path, status, _ in ex.map(lambda j: review_seat(j[0], j[1], args, texts), jobs):
                print(f"{path}: {status}", flush=True)
        print(f"paid this run: ${SPENT[0]:.2f}")
    summary(args.paths)
