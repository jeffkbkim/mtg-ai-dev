"""Arena Powered Cube deck pool for Claude games: decks of strong 17lands drafters from the 2025 run, plus a short game
plan per deck written once by Claude (players.py puts <deck>.plan.md in the seat's system prompt).

  python3 play/cube_deck_pool.py [--data <game_data csv.gz>] [--out engine/xmage/decks/cube-2025] [--decks 40]
      [--min-bucket 0.60] [--per-colors 3] [--plans] [--model claude-opus-5-5] [--effort medium] [--parallel 5]

Eligibility (the same idea as good_deck_pool_v2.py, without its two-colour and limited-curve rules, which don't fit
Cube decks): a draft's deck is its most-played build, played >= --min-build-games (3) games, exactly 40 cards, every
card in engine/vocab/cube_numbers.tsv (XMage lacks the six Arena-only cube cards: CubeList.MISSING); the drafter's
user_game_win_rate_bucket >= --min-bucket and user_n_games_bucket >= 100. Companions in the sideboard are ignored
(the deck is played without one).
Choice: highest drafter bucket first, then most games with the build, then a hash of the draft id; at most
--per-colors decks per main-colour combination (17lands' main_colors), so archetypes spread.
Writes <out>/cube_NN.dck ("NAME:cube_NN ..." marks it as a Cube deck for players.deck_set), manifest.json, and with
--plans <out>/cube_NN.plan.md (cached: an existing plan is kept).
"""
import argparse, csv, gzip, hashlib, json, os, subprocess, sys, tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "play"))
from render import card_text, load_card_text  # noqa: E402

DATA = Path("/mnt/project-files/data/17lands/cube/game_data_public.Cube_-_Powered.PremierDraft.csv.gz")


def load_numbers(path):
    """XMage name -> "SET:number" (engine/xmage SetNumbers with -Dmtg.set=CUBE)."""
    out = {}
    for line in Path(path).read_text().splitlines():
        num, name = line.split("\t")
        out[name] = num
    return out


def parse(path):
    """draft_id -> {bucket, n_games, builds: {build_index: {games, wins, colors, cards}}}"""
    drafts = {}
    with gzip.open(path, "rt", newline="") as f:
        r = csv.reader(f)
        head = next(r)
        col = {h: i for i, h in enumerate(head)}
        deck_cols = [(i, h[5:]) for i, h in enumerate(head) if h.startswith("deck_")]
        for row in r:
            d = row[col["draft_id"]]
            info = drafts.setdefault(d, {"draft_id": d, "bucket": row[col["user_game_win_rate_bucket"]],
                                         "n_games": row[col["user_n_games_bucket"]], "rank": row[col["rank"]], "builds": {}})
            b = info["builds"].get(row[col["build_index"]])
            if b is None:
                b = info["builds"][row[col["build_index"]]] = {
                    "games": 0, "wins": 0, "colors": row[col["main_colors"]], "splash": row[col["splash_colors"]],
                    "cards": [(name, int(row[i])) for i, name in deck_cols if row[i] not in ("", "0")]}
            b["games"] += 1
            b["wins"] += row[col["won"]] == "True"
    return drafts


def num(x):
    try:
        return float(x)
    except ValueError:
        return 0.0


def choose(drafts, numbers, args):
    cands = []
    for d in drafts.values():
        if num(d["bucket"]) < args.min_bucket or num(d["n_games"]) < 100:
            continue
        b = max(d["builds"].values(), key=lambda x: x["games"])
        if b["games"] < args.min_build_games or sum(n for _, n in b["cards"]) != 40:
            continue
        if any(name not in numbers for name, _ in b["cards"]):
            continue
        cands.append((d, b))
    cands.sort(key=lambda x: (-num(x[0]["bucket"]), -x[1]["games"], hashlib.sha256(x[0]["draft_id"].encode()).hexdigest()))
    picked, per = [], Counter()
    for d, b in cands:
        if per[b["colors"]] >= args.per_colors:
            continue
        per[b["colors"]] += 1
        picked.append((d, b))
        if len(picked) == args.decks:
            break
    return len(cands), picked


SYSTEM = """You are an expert Magic: The Gathering cube player (Arena Powered Cube: a 540-card singleton Vintage cube
with the Power Nine, fast mana and many archetypes, best of one, 40-card decks). You write a short game plan for a
player who will pilot the deck you are given. Plain text, one line per label, each label once, in this order:
Archetype:, Wins by:, Key cards:, Synergies:, Mulligan:, Early turns:, Fast mana:, Against aggro:, Against control:.
Each line at most 300 characters. Name only cards in the deck list (the opponent's possible cards are covered
elsewhere). Be concrete: which cards to lead with, what to hold, when to spend one-shot mana like Black Lotus, which
card to tutor for. No preamble."""


def plan_prompt(cards, texts, meta):
    lines = [f"Deck (17lands {meta}):"]
    for name, n in sorted(cards, key=lambda x: (texts.get(x[0], {}).get("mana_value", 0), x[0])):
        lines.append(f"{n}x {card_text(texts[name]) if name in texts else name}")
    return "\n".join(lines)


def ask(text, model, effort, timeout_s=600):
    work = tempfile.mkdtemp(prefix="claude-cube-plan-")
    Path(work, "system.txt").write_text(SYSTEM)
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID")}
    env["CLAUDE_EFFORT"] = effort
    env["PATH"] = f"{Path.home()}/.local/bin:" + env.get("PATH", "")
    p = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--model", model, "--effort", effort,
         "--system-prompt-file", "system.txt", "--tools", "", "--strict-mcp-config", "--setting-sources", "",
         "--no-session-persistence"],
        input=text, cwd=work, env=env, capture_output=True, text=True, timeout=timeout_s)
    out = json.loads(p.stdout)
    if out.get("is_error"):
        raise RuntimeError(f"plan error: {out.get('result')}")
    return (out.get("result") or "").strip(), out.get("total_cost_usd") or 0.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", default=str(DATA))
    p.add_argument("--numbers", default=str(ROOT / "engine/vocab/cube_numbers.tsv"))
    p.add_argument("--out", default=str(ROOT / "engine/xmage/decks/cube-2025"))
    p.add_argument("--decks", type=int, default=40)
    p.add_argument("--min-bucket", type=float, default=0.60)
    p.add_argument("--min-build-games", type=int, default=3)
    p.add_argument("--per-colors", type=int, default=3)
    p.add_argument("--plans", action="store_true")
    p.add_argument("--model", default="claude-opus-5-5"); p.add_argument("--effort", default="medium")
    p.add_argument("--parallel", type=int, default=5)
    args = p.parse_args()

    numbers = load_numbers(args.numbers)
    texts = load_card_text()
    n_cands, picked = choose(parse(args.data), numbers, args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for k, (d, b) in enumerate(picked):
        name = f"cube_{k:02d}"
        colors = b["colors"] + (f"+{b['splash']}" if b["splash"] else "")
        meta = (f"{colors}, drafter win-rate bucket {num(d['bucket']):.2f}, {d['rank'] or 'unranked'}, "
                f"{b['wins']}-{b['games'] - b['wins']} with this build")
        lines = [f"NAME:{name} · {meta}"]
        for card, n in sorted(b["cards"], key=lambda x: x[0]):
            lines.append(f"{n} [{numbers[card]}] {card}")
        (out / f"{name}.dck").write_text("\n".join(lines) + "\n")
        manifest.append({"deck": f"{name}.dck", "draft_id": d["draft_id"], "colors": b["colors"], "splash": b["splash"],
                         "drafter_bucket": d["bucket"], "drafter_games_bucket": d["n_games"], "rank": d["rank"],
                         "build_games": b["games"], "build_wins": b["wins"], "meta": meta})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"candidates {n_cands}, written {len(picked)} decks to {out}; colours {dict(Counter(m['colors'] for m in manifest))}")

    if args.plans:
        todo = [(m, out / m["deck"].replace(".dck", ".plan.md")) for m in manifest]
        todo = [(m, path) for m, path in todo if not path.exists()]
        cards = {m["deck"]: b["cards"] for m, (_, b) in zip(manifest, picked)}

        def one(item):
            m, path = item
            reply, cost = ask(plan_prompt(cards[m["deck"]], texts, m["meta"]), args.model, args.effort)
            path.write_text(reply + "\n")
            return cost

        with ThreadPoolExecutor(args.parallel) as ex:
            costs = list(ex.map(one, todo))
        print(f"plans written {len(costs)}, cost ${sum(costs):.2f}")


if __name__ == "__main__":
    main()
