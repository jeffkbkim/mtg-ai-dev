"""Review the strong 17lands deck pool and mark the best decks tier 2 (★★); every other deck stays tier 1 (★).

  python3 play/review_decks.py [<pool dir>] [--model claude-opus-5-5] [--effort medium] [--parallel 5] [--limit N]
      [--no-review] [--min-rating 4] [--min-bucket 0.60] [--ranks <rank> ...] [--weak-archetype 0.53]
      [--color-ratings <17lands color_ratings json>] [--card-ratings <17lands card_ratings json>] [--game-data <csv.gz>]

Pool dir defaults to engine/xmage/decks/17lands-good (built by good_deck_pool.py). Per deck:
- stats from the card text file: curve of nonland cards by mana value (a Room counts its cheaper door, an X spell
  counts X=1), creatures, other spells, lands, fixing lands (a land making two of the deck's colors, any color, or
  fetching a basic), removal tagged by regex on rules text ("hard": destroy/exile/damage/-N/-N/fight/-1/-1 counters
  aimed at a target; "soft": bounce, tap-down, can't-block auras), and the 17lands win rate of its main-color archetype
  (--color-ratings, combine_splash=true);
- one headless `claude -p` review (no tools) of the decklist with card text and stats; record, rank and drafter are
  left out so the rating is the build's alone. Replies are cached in <pool>/review_cache.json by prompt hash.
Red flags: 3+ main colors with fewer than 3 fixing lands; fewer than 5 two-drops or 5+ cards at 6+; lands outside
16-18; archetype win rate below --weak-archetype. Tier 2 = rating >= --min-rating, no red flag, drafter bucket >=
--min-bucket and rank in --ranks (any rank when --ranks is empty, the default; bucket alone when rank is missing). Drop candidates (listed, never deleted):
rating <= 2. --game-data adds a top-player GIH WR (drafter bucket >= 0.62, cached under ~/mtg-data/17lands/ratings/)
and a second deck score; --card-ratings compares gih_wr.json with 17lands' published ratings. Writes <pool>/REVIEW.md
and adds stats, review and tier to each deck in <pool>/manifest.json.
"""
import argparse, csv, gzip, hashlib, json, math, os, re, subprocess, sys, tempfile, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import card_text, clean, load_card_text

ROOT = Path(__file__).resolve().parent.parent
RATINGS = Path.home() / "mtg-data/17lands/ratings"
SET = os.environ.get("MTG_SET", "DSK").upper()  # MTG_SET=FDN reviews Foundations decks
SET_NAMES = {"DSK": "Duskmourn", "FDN": "Foundations"}
WUBRG = "WUBRG"

SYSTEM = """You are a strong Magic: The Gathering Limited player reviewing a 40-card Duskmourn (DSK) Premier Draft deck.
You get the decklist with each nonland card's rules text, the lands, and a few counts. Judge the build itself: card
quality for DSK Limited, curve, creature count, removal, mana and color requirements, and whether the cards work as a
plan. Do not guess the deck's results.
Reply with only one JSON object, no other text:
{"archetype": "<short name, e.g. 'UW fliers', 'RG aggro', 'BG self-mill', 'pile of good cards'>",
 "coherent": true or false, "concerns": ["<one or two words each, e.g. 'curve', 'lands', 'colors', 'removal', 'few creatures'>"],
 "rating": <integer 1-5, how a strong Limited player would rate this build; 3 = a fine deck, 5 = exceptional>,
 "verdict": "<one line>"}"""
# v2 (2026-10-26, experiments/reviewer_bias): v1 marked UG and manifest dread decks down for "few creatures" when
# their manifest dread, tokens and recursion make the bodies up (residual -0.34 for UG against card quality)
BODIES_RULE = """
Bodies: count creature cards plus the cards that put creatures onto the battlefield: manifest dread (each puts a
face-down 2/2 creature onto the battlefield), creature tokens and creature recursion. A deck with enough bodies has
enough creatures even with fewer creature cards; the counts line gives the body count when it differs."""
SYSTEM = SYSTEM.replace("Duskmourn (DSK)", f"{SET_NAMES[SET]} ({SET})").replace("for DSK Limited", f"for {SET} Limited")
SYSTEMS = {"v1": SYSTEM, "v2": SYSTEM.replace("Do not guess the deck's results.", "Do not guess the deck's results." + BODIES_RULE)}
SYSTEM = SYSTEMS[os.environ.get("REVIEW_SYSTEM", "v2")]  # v2 from 2026-10-26; REVIEW_SYSTEM=v1 for the earlier ratings
if SET != "DSK":  # manifest dread is a Duskmourn mechanic
    SYSTEM = SYSTEM.replace("manifest dread (each puts a\nface-down 2/2 creature onto the battlefield), ", "")
SYSTEM_SHA = hashlib.sha256(SYSTEM.encode()).hexdigest()[:12]

HARD = [r"destroy (?:target|all|up to one target)[\w ,-]*?(creature|permanent)", r"exile (?:target|up to one target)[\w ,-]*?(creature|permanent)",
        r"damage[\w ,'-]*? to (?:up to one |another |each of up to \w+ )?(?:target creatures?|any target|any other target|each other creature|the creature an opponent controls)",
        r"target creature[\w ]* gets -\d+/-\d+", r"gets -x/-x", r"fights? (?:target|up to one|another)",
        r"-1/-1 counters? on (?:target|each|up to)", r"(?:opponent|player) sacrifices", r"puts it on their choice of the top or bottom"]
SOFT = [r"return (?:up to one )?target [\w ]*?(creature|permanent)[\w ]* to (?:its|their) owner's hand",
        r"tap (?:up to one )?target creature", r"counter target creature",
        r"enchanted creature (?:can't attack or block|doesn't untap|loses all abilities|gets -\d+/-0)"]


def mana_value(c):
    if "left" in c:
        return min(door_mv(h["cost"]) for h in (c["left"], c["right"]))
    return c["mana_value"] + c["cost"].count("{X}")  # X = 1


def door_mv(cost):
    return sum(int(s) if s.isdigit() else (0 if s == "X" else 1) for s in re.findall(r"\{([^}]+)\}", cost))


def rules(c):
    rs = list(c.get("rules", []))
    for h in ("left", "right"):
        if h in c:
            rs += c[h]["rules"]
    return clean(" ".join(rs)).replace("{this}", "this")


def removal_tag(c):
    t = re.sub(r"target [\w ]*?creature you control", "", rules(c).lower())  # own-creature targets are not removal
    if any(re.search(p, t) for p in HARD):
        return "hard"
    if any(re.search(p, t) for p in SOFT):
        return "soft"
    return None


def is_fixer(c, colors):
    t = rules(c)
    made = set(re.findall(r"\{([WUBRG])\}", " ".join(r for r in c.get("rules", []) if "Add" in r)))
    return ("any color" in t or "search your library for a basic land" in t.lower() or len(made & set(colors)) >= 2)


BODY = [r"create[\w ,'-]*?\d+/\d+[\w ,'-]*?creature token", r"create[\w ,'-]*?creature tokens?", r"\bmanifest(?: dread)?\b",
        r"return[\w ,'-]*?creature cards?[\w ,'-]*? from (?:your|a) graveyard to the battlefield",
        r"return (?:this card|it|[\w ,'-]*?) from your graveyard to the battlefield"]


def makes_bodies(c):
    """A noncreature card that puts creatures on the battlefield: token makers, manifest dread (Rooms too) and creature
    recursion. Jeff 2026-10-25: these count as bodies for the deck checks, beside creature cards."""
    t = rules(c).lower()
    return any(re.search(p, t) for p in BODY)


def deck_stats(d, texts, color_wr):
    curve, crea, spells, lands, fix, hard, soft, makers = Counter(), 0, 0, 0, 0, [], [], 0
    colors = d["main_colors"] + d["splash_colors"]
    for name, n in d["deck"].items():
        c = texts[name]
        if "Land" in c["types"] and "left" not in c and "Creature" not in c["types"]:
            lands += n; fix += n * is_fixer(c, colors)
            continue
        curve[min(mana_value(c), 6)] += n
        if "Creature" in c["types"]:
            crea += n
        else:
            spells += n
            makers += n * makes_bodies(c)
        tag = removal_tag(c)
        (hard if tag == "hard" else soft if tag == "soft" else []).extend([name] * n)
    s = {"curve": [curve[i] for i in range(1, 7)], "zero_drops": curve[0], "creatures": crea, "body_makers": makers, "bodies": crea + makers, "noncreature_spells": spells,
         "lands": lands, "fixing_lands": fix, "removal": len(hard), "soft_removal": len(soft),
         "removal_cards": sorted(set(hard)), "soft_removal_cards": sorted(set(soft)),
         "archetype_wr": color_wr.get(d["main_colors"])}
    return s


def red_flags(d, s, weak):
    f = []
    if len(d["main_colors"]) >= 3 and s["fixing_lands"] < 3:
        f.append(f"{len(d['main_colors'])} main colors, {s['fixing_lands']} fixing lands")
    if s["curve"][1] < 5:
        f.append(f"{s['curve'][1]} two-drops")
    if s["curve"][5] >= 5:
        f.append(f"{s['curve'][5]} cards at 6+")
    if not 16 <= s["lands"] <= 18:
        f.append(f"{s['lands']} lands")
    if s["archetype_wr"] is not None and s["archetype_wr"] < weak:
        f.append(f"weak archetype {d['main_colors']} {s['archetype_wr']:.1%}")
    return f


def prompt(d, s, texts):
    colors = d["main_colors"] + (f" splashing {d['splash_colors']}" if d["splash_colors"] else "")
    out = [f"Main colors {colors}. Curve of nonland cards by mana value 1/2/3/4/5/6+: {'/'.join(map(str, s['curve']))}"
           + (f" (plus {s['zero_drops']} at 0)" if s["zero_drops"] else "") + f". {s['creatures']} creatures"
           + (f" ({s['bodies']} bodies counting {s['body_makers']} token makers{', manifest dread' if SET == 'DSK' else ''} and creature recursion)" if s.get('body_makers') else "")
           + ", "
           f"{s['noncreature_spells']} other spells, {s['lands']} lands ({s['fixing_lands']} fixing). Removal by a "
           f"rough text tag: {s['removal']} hard, {s['soft_removal']} soft.", "", "Nonland cards:"]
    lands = []
    for name, n in sorted(d["deck"].items(), key=lambda kv: (mana_value(texts[kv[0]]), kv[0])):
        c = texts[name]
        if "Land" in c["types"] and "left" not in c and "Creature" not in c["types"]:
            lands.append(f"{n} {name}")
        else:
            out.append(f"{n}x {clean(card_text(c)).replace('{this}', 'this')}")
    out += ["", "Lands: " + ", ".join(lands)]
    return "\n".join(out)


def ask(text, model, effort, timeout_s):
    work = tempfile.mkdtemp(prefix="claude-deck-review-")
    Path(work, "system.txt").write_text(SYSTEM)
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID")}
    env["CLAUDE_EFFORT"] = effort
    env["DISABLE_PROMPT_CACHING"] = "1"
    env["PATH"] = f"{Path.home()}/.local/bin:" + env.get("PATH", "")
    p = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--model", model, "--effort", effort,
         "--system-prompt-file", "system.txt", "--tools", "", "--strict-mcp-config", "--setting-sources", "",
         "--no-session-persistence"],
        input=text, cwd=work, env=env, capture_output=True, text=True, timeout=timeout_s)
    out = json.loads(p.stdout)
    if out.get("is_error"):
        raise RuntimeError(f"reviewer error: {out.get('result')}")
    return out.get("result") or "", out.get("total_cost_usd") or 0.0


def parse(reply):
    i, j = reply.find("{"), reply.rfind("}")
    try:
        r = json.loads(reply[i:j + 1]) if 0 <= i < j else None
    except json.JSONDecodeError:
        return None
    ok = isinstance(r, dict) and isinstance(r.get("rating"), int) and 1 <= r["rating"] <= 5
    return {k: r.get(k) for k in ("archetype", "coherent", "concerns", "rating", "verdict")} if ok else None


def review(key, text, args, cache):
    if key in cache and cache[key].get("review"):
        return key, "cached"
    cost, reply, parsed = 0.0, None, None
    for _ in range(2):  # one retry on a failed call or unreadable reply
        try:
            reply, c = ask(text, args.model, args.effort, args.timeout)
            cost += c
        except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            reply = f"[error] {e}"
            continue
        if (parsed := parse(reply)):
            break
    cache[key] = {"review": parsed, "reply": reply, "cost_usd": round(cost, 5), "model": args.model,
                  "effort": args.effort, "system_sha": SYSTEM_SHA}
    return key, f"${cost:.3f}"


def spearman(a, b):
    def ranks(x):
        order = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    return pearson(ranks(a), ranks(b))


def pearson(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return num / math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))


def top_gih(path, cache_path, min_bucket=0.62):
    if cache_path.exists():
        return json.loads(cache_path.read_text())
    g = {}
    with gzip.open(path, "rt", newline="") as f:
        r = csv.reader(f)
        head = next(r)
        col = {h: i for i, h in enumerate(head)}
        cards = [h[5:] for h in head if h.startswith("deck_")]
        hand = [(col["opening_hand_" + c], col["drawn_" + c], c) for c in cards]
        for row in r:
            b = row[col["user_game_win_rate_bucket"]]
            if not b or float(b) < min_bucket - 1e-9:
                continue
            won = row[col["won"]] == "True"
            for i, j, c in hand:
                if row[i] not in ("0", "") or row[j] not in ("0", ""):
                    x = g.setdefault(c, [0, 0]); x[0] += 1; x[1] += won
    out = {"min_bucket": min_bucket, "cards": {c: {"games": n, "wins": w, "wr": round(w / n, 5)} for c, (n, w) in g.items()}}
    cache_path.write_text(json.dumps(out, indent=1))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("pool", nargs="?", default=str(ROOT / "engine/xmage/decks/17lands-good"))
    p.add_argument("--model", default="claude-opus-5-5"); p.add_argument("--effort", default="medium")
    p.add_argument("--parallel", type=int, default=5); p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--limit", type=int); p.add_argument("--no-review", action="store_true")
    p.add_argument("--min-rating", type=int, default=4); p.add_argument("--min-bucket", type=float, default=0.60)
    p.add_argument("--ranks", nargs="*", default=[])
    p.add_argument("--weak-archetype", type=float, default=0.53)
    p.add_argument("--color-ratings", default=str(RATINGS / "dsk_color_ratings.json"))
    p.add_argument("--card-ratings", default=str(RATINGS / "dsk_card_ratings_all.json"))
    p.add_argument("--game-data", default=str(Path.home() / "mtg-data/17lands/DSK/game_data_public.DSK.PremierDraft.csv.gz"))
    args = p.parse_args()

    pool = Path(args.pool)
    man = json.loads((pool / "manifest.json").read_text())
    gih_path = pool / "gih_wr.json" if (pool / "gih_wr.json").exists() else ROOT / "engine/xmage/decks/17lands-good/gih_wr.json"
    gih = json.loads(gih_path.read_text())  # card win rates for all games: the same file for every pool
    texts = load_card_text()
    color_wr, all_wr = {}, 0.0
    if Path(args.color_ratings).exists():
        cr = json.loads(Path(args.color_ratings).read_text())
        color_wr = {r["short_name"]: r["wins"] / r["games"] for r in cr if not r["is_summary"] and r["games"]}
        all_wr = next((r["wins"] / r["games"] for r in cr if r["short_name"] == "All"), 0.0)
    # 17lands writes colors in WUBRG order; the game data's main_colors already uses it.
    cache_path = pool / "review_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    decks, todo = man["decks"], []
    for d in decks:
        d["_stats"] = deck_stats(d, texts, color_wr)
        d["_prompt"] = prompt(d, d["_stats"], texts)
        d["_key"] = hashlib.sha256((SYSTEM_SHA + args.model + args.effort + d["_prompt"]).encode()).hexdigest()[:16]
        if not (d["_key"] in cache and cache[d["_key"]].get("review")):
            todo.append(d)
    if not args.no_review:
        todo = todo[:args.limit] if args.limit else todo
        with ThreadPoolExecutor(args.parallel) as ex:
            for i, (key, how) in enumerate(ex.map(lambda d: review(d["_key"], d["_prompt"], args, cache), todo)):
                print(f"{todo[i]['file']}: {how}", flush=True)
                cache_path.write_text(json.dumps(cache, indent=1, ensure_ascii=False))

    # 17lands cross-checks
    notes = []
    if color_wr:
        pool_cols = Counter(d["main_colors"] for d in decks)
        notes.append("17lands archetype WR (main colors, all players): " + ", ".join(
            f"{c} {color_wr[c]:.1%} ({n} decks)" for c, n in pool_cols.most_common() if c in color_wr)
            + f"; all decks {all_wr:.1%}. Weak archetype: below {args.weak_archetype:.0%}.")
    tg = top_gih(Path(args.game_data), RATINGS / "dsk_gih_top.json") if Path(args.game_data).exists() else None
    if tg:
        for d in decks:
            if "deck_score" not in d:  # a pool built without one (17lands-r2): the same mean GIH WR of nonland cards
                pairs = [(n, gih[name]["wr"]) for name, n in d["deck"].items() if not gih[name]["land"]]
                d["deck_score"] = round(sum(n * w for n, w in pairs) / sum(n for n, _ in pairs), 5)
            num = den = 0
            for name, n in d["deck"].items():
                if not gih[name]["land"] and name in tg["cards"]:
                    num += n * tg["cards"][name]["wr"]; den += n
            d["_stats"]["deck_score_top"] = round(num / den, 5)
        rho = spearman([d["deck_score"] for d in decks], [d["_stats"]["deck_score_top"] for d in decks])
        common = [c for c, v in gih.items() if not v["land"] and v["games"] >= 1000 and tg["cards"].get(c, {}).get("games", 0) >= 500]
        r = pearson([gih[c]["wr"] for c in common], [tg["cards"][c]["wr"] for c in common])
        notes.append(f"Top-player GIH WR (drafter bucket >= {tg['min_bucket']}) vs all-player GIH WR: Pearson {r:.3f} over "
                     f"{len(common)} nonland cards; deck score from it vs deck score: Spearman {rho:.3f} over {len(decks)} decks.")
    if Path(args.card_ratings).exists():
        pub = {c["name"]: c for c in json.loads(Path(args.card_ratings).read_text())}
        both = [c for c in gih if c in pub and (pub[c].get("ever_drawn_game_count") or 0) >= 500 and gih[c]["games"] >= 500]
        total = sum(c.get("game_count") or 0 for c in pub.values())
        if len(both) >= 20:
            r = pearson([gih[c]["wr"] for c in both], [pub[c]["ever_drawn_win_rate"] for c in both])
            diff = sorted(((gih[c]["wr"] - pub[c]["ever_drawn_win_rate"]) * 100, c) for c in both)
            big = [f"{c} {x:+.1f}" for x, c in diff if abs(x) > 1]
            notes.append(f"gih_wr.json vs 17lands published GIH WR: Pearson {r:.3f} over {len(both)} cards; differing by "
                         f"more than 1 point: {', '.join(big) or 'none'}.")
        else:
            notes.append(f"17lands' published card ratings could not be used: the endpoint returned {len(pub)} cards but only "
                         f"{total} games in all ({len(both)} cards with 500+ GIH games), whatever date range or user_group was asked.")

    # tiers
    rows, total_cost = [], 0.0
    for d in decks:
        s, c = d["_stats"], cache.get(d["_key"], {})
        total_cost += c.get("cost_usd", 0.0)
        rv = c.get("review")
        flags = red_flags(d, s, args.weak_archetype)
        bucket = float(d["user_win_rate_bucket"] or 0)
        strong = bucket >= args.min_bucket - 1e-9 and (not args.ranks or not d["rank"] or d["rank"] in args.ranks)
        tier2 = bool(rv) and rv["rating"] >= args.min_rating and not flags and strong
        drop = bool(rv) and rv["rating"] <= 2
        s["red_flags"] = flags
        rows.append((d, s, rv, flags, bucket, tier2, drop))
    if any(r[2] is None for r in rows):
        print(f"{sum(r[2] is None for r in rows)} decks have no review yet; REVIEW.md and manifest not written.")
        for d, s, rv, flags, *_ in rows:
            print(d["file"], d["main_colors"], d["splash_colors"], s["curve"], s["creatures"], s["removal"], s["soft_removal"],
                  s["lands"], s["fixing_lands"], flags)
        print("\n".join(notes))
        return

    for d, s, rv, flags, bucket, tier2, drop in rows:
        d["tier"] = 2 if tier2 else 1
        d["review"] = rv
        d["stats"] = s
        for k in ("_stats", "_prompt", "_key"):
            d.pop(k)
    (pool / "manifest.json").write_text(json.dumps(man, indent=1, ensure_ascii=False) + "\n")

    n2 = sum(r[5] for r in rows)
    ranks = "/".join(args.ranks)
    strict = sum(r[2]["rating"] >= args.min_rating and not r[3] and r[4] >= 0.64 - 1e-9
                 and (not r[0]["rank"] or r[0]["rank"] in ("diamond", "mythic")) for r in rows)
    md = [f"# Review of the {len(rows)} strong 17lands DSK decks", "",
          f"Made by `python3 play/review_decks.py` ({args.model}, effort {args.effort}, one headless review per deck with "
          f"no tools; total cost ${total_cost:.2f}, replies cached in `review_cache.json`). The reviewer saw the decklist "
          "with card text, the curve and counts, but not the record, rank or drafter, so its rating is of the build alone.",
          "", f"- Curve: nonland cards at mana value 1/2/3/4/5/6+ (a Room at its cheaper door, X spells at X=1). Removal: "
          "a rough rules-text tag, hard (soft in brackets: bounce, tap-down, can't-block auras).",
          f"- Archetype WR: 17lands' win rate for the deck's main colors, all DSK PremierDraft games, splashes combined.",
          f"- Red flags: 3+ main colors with fewer than 3 fixing lands; fewer than 5 two-drops or 5+ cards at 6+; lands "
          f"outside 16-18; archetype WR below {args.weak_archetype:.0%}.",
          f"- Tier 2 (★★, {n2} decks): rating >= {args.min_rating}, no red flag, drafter win-rate bucket >= {args.min_bucket:.2f} "
          + (f"and rank {ranks} (bucket alone when rank is missing)" if args.ranks else "(any rank)")
          + f". Every other deck is tier 1 (★). Ratings: " + ", ".join(f"{k}: {v}" for k, v in sorted(Counter(r[2]['rating'] for r in rows).items()))
          + f". Only {sum(r[2]['rating'] >= args.min_rating and not r[3] for r in rows)} decks reach the rating with no red flag, "
          f"and a strong-drafter gate (bucket >= 0.64 and rank diamond/mythic) would leave {strict}, so the drafter gate is "
          "the pool's own floor (every deck is a 7-win trophy by a drafter at bucket >= 0.60).",
          f"- Drop candidates (rating <= 2, {sum(r[6] for r in rows)} decks) are listed but kept: "
          + ", ".join(f"{r[0]['file'][:-4]} ({'; '.join(r[3] + [', '.join(r[2]['concerns'][:2])])})" for r in rows if r[6]) + ".",
          ""] + [f"- {n}" for n in notes] + ["",
          "| deck | colors | archetype | curve | crea | removal | lands | arch WR | score | top score | record | rank | drafter | rating | tier | flags | verdict |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for d, s, rv, flags, bucket, tier2, drop in rows:
        col = d["main_colors"] + (f"+{d['splash_colors']}" if d["splash_colors"] else "")
        aw = f"{s['archetype_wr']:.1%}" if s["archetype_wr"] is not None else "-"
        ts = f"{s['deck_score_top']:.1%}" if "deck_score_top" in s else "-"
        md.append(f"| {d['file'][:-4]} | {col} | {rv['archetype']} | {'/'.join(map(str, s['curve']))} | {s['creatures']} | "
                  f"{s['removal']} ({s['soft_removal']}) | {s['lands']} ({s['fixing_lands']} fix) | {aw} | {d['deck_score']:.1%} | {ts} | "
                  f"{d['wins']}-{d['losses']} | {d['rank'] or '-'} | {bucket:.2f} | {rv['rating']}{' drop' if drop else ''} | "
                  f"{'★★' if tier2 else '★'} | {'; '.join(flags) or '-'} | {rv['verdict']} |")
    (pool / "REVIEW.md").write_text("\n".join(md) + "\n")
    print(f"tier 2: {n2}, tier 1: {len(rows) - n2}, drop candidates: {sum(r[6] for r in rows)}, total cost ${total_cost:.2f}")
    print("\n".join(notes))


if __name__ == "__main__":
    main()
