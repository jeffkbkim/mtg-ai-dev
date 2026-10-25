"""Proposal: a strong DSK deck pool chosen by build quality and the drafter's long-run win rate, not by record or GIH score.

  python3 play/good_deck_pool_v2.py [--data <game_data csv.gz>] [--out engine/xmage/decks/17lands-good-v2]
      [--thresholds 0.64 0.62 0.60 0.58] [--min-build-games 3] [--shortlist-per-pair 15] [--per-pair 10]
      [--no-review] [--model claude-opus-5-5] [--effort medium] [--parallel 5]

1. Candidates. Eligibility is deck_pool.py's: a draft's deck is its most-played build, 40 cards, every card in
   engine/vocab/dsk_numbers.tsv, never substituted. No win requirement; the build must have been played >= --min-build-games
   games, and the drafter's user_n_games_bucket must be >= --min-user-games (100). Colours (main/splash) are 17lands' for that build's rows. Then:
   - Jeff's colour rule: engine/playmat/dsk_starters.py two_colors() (2 main colours, at most one splash colour in
     <= 3 nonland cards with >= 3 lands making it), plus every nonland card's coloured pips within main+splash;
   - build checks (stats from play/review_decks.py deck_stats): 15-18 lands, >= --min-creatures creatures, >= 4
     two-drops, at most 3 cards at 6+ and at most 7 at 5+;
   - drafter user_game_win_rate_bucket >= the first --thresholds value at which every two-colour pair has at least
     --shortlist-per-pair candidates (or the last value).
2. Shortlist per pair: the --shortlist-per-pair candidates with the highest drafter bucket (then mana score, then a
   hash of the draft id). Each is reviewed by review_decks.py's reviewer with the same system prompt and user prompt, so
   ratings are comparable to 17lands-good/REVIEW.md; cache in <out>/review_cache.json (seeded read-only from
   17lands-good/review_cache.json when a prompt is identical).
3. Keep rating >= 3. Tier 2 = rating >= 4 and no build red flag (review_decks.red_flags without the weak-archetype flag,
   which is about the colour pair, not the build; it is recorded as "archetype_flag"). Up to --per-pair decks per pair,
   ranked by tier, rating, mana score, drafter bucket. Record and GIH deck score are kept as info only.
Mana score (10 = best): for each main colour, sources = lands that can make it (basics, duals, Terramorphic Expanse,
Valgavoth's Lair); need = 7, or 8 if the colour is in >= 8 nonland cards or any card needs two of its pips, or 9 if
a card of mana value <= 3 needs two of its pips; minus the shortfall below need, minus 0.5 per splash card, minus 1
more if a splash card needs two splash pips or the splash has fewer than 4 sources.
Writes <out>/good_NN.dck (00 = rank 0), manifest.json and prints counts; README.md is written by hand from them.
"""
import argparse, csv, gzip, hashlib, json, re, sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "play")); sys.path.insert(0, str(ROOT / "engine/playmat"))
import review_decks as rd  # noqa: E402  (reviewer, prompt, stats, red flags)
from dsk_starters import two_colors  # noqa: E402  (Jeff's colour rule, unchanged)

PAIRS = ["WU", "UB", "BR", "RG", "WG", "WB", "UR", "BG", "WR", "UG"]  # 17lands' WUBRG-ordered names
BASICS = {"Plains": "W", "Island": "U", "Swamp": "B", "Mountain": "R", "Forest": "G"}
RANK = {"bronze": "Bronze", "silver": "Silver", "gold": "Gold", "platinum": "Plat", "diamond": "Diamond", "mythic": "Mythic"}


def parse(path, numbers):
    drafts, builds = {}, defaultdict(dict)
    with gzip.open(path, "rt", newline="") as f:
        r = csv.reader(f)
        head = next(r)
        col = {h: i for i, h in enumerate(head)}
        deck_cols = [(i, h[5:]) for i, h in enumerate(head) if h.startswith("deck_")]
        for row in r:
            d, b = row[col["draft_id"]], row[col["build_index"]]
            info = drafts.get(d)
            if info is None:
                info = drafts[d] = {"draft_id": d, "games": 0, "wins": 0, "rank": row[col["rank"]],
                                    "user_win_rate_bucket": row[col["user_game_win_rate_bucket"]],
                                    "user_n_games_bucket": row[col["user_n_games_bucket"]]}
            info["games"] += 1
            info["wins"] += row[col["won"]] == "True"
            bd = builds[d].get(b)
            if bd is None:
                deck = {name: int(row[i]) for i, name in deck_cols if row[i] not in ("0", "")}
                bd = builds[d][b] = {"deck": deck, "games": 0, "wins": 0, "main_colors": row[col["main_colors"]],
                                     "splash_colors": row[col["splash_colors"]]}
            bd["games"] += 1
            bd["wins"] += row[col["won"]] == "True"
    skipped, ok = Counter(), []
    for d, info in drafts.items():
        b, bd = max(builds[d].items(), key=lambda kv: kv[1]["games"])
        if sum(bd["deck"].values()) != 40:
            skipped["not 40 cards"] += 1; continue
        if any(c not in numbers for c in bd["deck"]):
            skipped["card not in XMage DSK"] += 1; continue
        info.update(build_index=b, build_games=bd["games"], build_wins=bd["wins"], losses=info["games"] - info["wins"],
                    deck=bd["deck"], main_colors=bd["main_colors"], splash_colors=bd["splash_colors"])
        ok.append(info)
    return len(drafts), dict(skipped), ok


def is_land(c):
    return "Land" in c["types"] and "left" not in c and "Creature" not in c["types"]


def makes(name, c):
    """Colours a land can make (all five for Terramorphic Expanse and Valgavoth's Lair)."""
    if name in BASICS:
        return {BASICS[name]}
    t = " ".join(c["rules"])
    if "basic land" in t.lower() or "any color" in t or "chosen color" in t:
        return set("WUBRG")
    return set(re.findall(r"Add \{([WUBRG])\}", t))


def pips(c):
    """Per colour, the most pips any one castable half asks for (hybrid/Phyrexian symbols are not counted)."""
    costs = [h["cost"] for h in (c["left"], c["right"])] if "left" in c else [c["cost"]]
    out = Counter()
    for cost in costs:
        for x, n in Counter(re.findall(r"\{([WUBRG])\}", cost)).items():
            out[x] = max(out[x], n)
    return out


def mana(d, texts):
    main, splash = d["main_colors"], d["splash_colors"]
    sources, cards, double, early_double, off = Counter(), Counter(), set(), set(), Counter()
    for name, n in d["deck"].items():
        c = texts[name]
        if is_land(c):
            for x in makes(name, c):
                sources[x] += n
            continue
        for x, k in pips(c).items():
            cards[x] += n
            if x not in main + splash:
                off[name] += n
            if k >= 2:
                double.add(x)
                if rd.mana_value(c) <= 3:
                    early_double.add(x)
    score, per = 10.0, {}
    for x in main:
        need = 9 if x in early_double else 8 if (x in double or cards[x] >= 8) else 7
        short = max(0, need - sources[x])
        score -= short
        per[x] = {"sources": sources[x], "need": need, "cards": cards[x]}
    if splash:
        score -= 0.5 * cards[splash] + (1 if splash in double or sources[splash] < 4 else 0)
        per[splash] = {"sources": sources[splash], "cards": cards[splash], "splash": True}
    return round(score, 2), per, dict(off)


def build_fails(s, min_creatures):
    f = []
    if not 15 <= s["lands"] <= 18:
        f.append("lands")
    if s.get("bodies", s["creatures"]) < min_creatures:  # Jeff 2026-10-25: token makers, manifest dread, recursion count
        f.append("creatures")
    if s["curve"][1] < 4:
        f.append("two-drops")
    if s["curve"][5] > 3 or s["curve"][4] + s["curve"][5] > 7:
        f.append("top end")
    return f


def tie(d):
    return hashlib.sha256(d["draft_id"].encode()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", default=str(Path.home() / "mtg-data/17lands/DSK/game_data_public.DSK.PremierDraft.csv.gz"))
    p.add_argument("--numbers", default=str(ROOT / "engine/vocab/dsk_numbers.tsv"))
    p.add_argument("--out", default=str(ROOT / "engine/xmage/decks/17lands-good-v2"))
    p.add_argument("--current", default=str(ROOT / "engine/xmage/decks/17lands-good"))
    p.add_argument("--parse-cache", help="json.gz of parsed eligible drafts (made if missing; keep it outside Git)")
    p.add_argument("--thresholds", type=float, nargs="+", default=[0.66, 0.64, 0.62, 0.60])
    p.add_argument("--min-user-games", type=int, default=100, help="user_n_games_bucket floor: the WR bucket of a drafter with few games is noise")
    p.add_argument("--min-build-games", type=int, default=3); p.add_argument("--min-creatures", type=int, default=13)
    p.add_argument("--shortlist-per-pair", type=int, default=15); p.add_argument("--per-pair", type=int, default=10)
    p.add_argument("--keep-rating", type=int, default=3); p.add_argument("--min-rating", type=int, default=4)
    p.add_argument("--pairs", nargs="+", default=PAIRS, help="only these colour pairs (e.g. a top-up for one pair)")
    p.add_argument("--min-wins", type=int, default=0, help="draft record floor (7 = trophy decks only)")
    p.add_argument("--exclude", nargs="*", default=[], help="manifest.json files whose draft ids are left out")
    p.add_argument("--no-review", action="store_true")
    p.add_argument("--model", default="claude-opus-5-5"); p.add_argument("--effort", default="medium")
    p.add_argument("--parallel", type=int, default=5); p.add_argument("--timeout", type=int, default=600)
    args = p.parse_args()

    numbers = {}
    for line in Path(args.numbers).read_text().splitlines():
        num, name = line.split("\t", 1)
        numbers[name] = num
    pc = Path(args.parse_cache) if args.parse_cache else None
    if pc and pc.exists():
        n_drafts, skipped, ok = json.loads(gzip.decompress(pc.read_bytes()))
    else:
        n_drafts, skipped, ok = parse(args.data, numbers)
        if pc:
            pc.write_bytes(gzip.compress(json.dumps([n_drafts, skipped, ok]).encode()))
    texts = rd.load_card_text()
    cr = json.loads((rd.RATINGS / "dsk_color_ratings.json").read_text())
    color_wr = {r["short_name"]: r["wins"] / r["games"] for r in cr if not r["is_summary"] and r["games"]}
    gih = json.loads((Path(args.current) / "gih_wr.json").read_text())
    bucket = lambda d: float(d["user_win_rate_bucket"] or 0)

    pairs = args.pairs
    excluded = set()
    for m in args.exclude:
        excluded |= {x["draft_id"] for x in json.loads(Path(m).read_text())["decks"]}
    funnel = Counter(eligible=len(ok))
    cands = []
    for d in ok:
        if d["main_colors"] not in pairs or d["draft_id"] in excluded:
            continue
        funnel["pair, not in an excluded pool"] += 1
        if int(d["wins"] or 0) < args.min_wins:
            continue
        funnel[f"wins >= {args.min_wins}"] += 1
        if d["build_games"] < args.min_build_games:
            continue
        funnel["build games ok"] += 1
        if int(d["user_n_games_bucket"] or 0) < args.min_user_games:
            continue
        funnel[f"drafter games bucket >= {args.min_user_games}"] += 1
        if not two_colors(d, texts):
            continue
        funnel["colour rule ok"] += 1
        d["mana_score"], d["mana"], off = mana(d, texts)
        if off:
            funnel["off-colour card (dropped)"] += 1; continue
        d["stats"] = rd.deck_stats(d, texts, color_wr)
        fails = build_fails(d["stats"], args.min_creatures)
        for x in fails:
            funnel[f"fails {x}"] += 1
        if fails:
            continue
        funnel["build checks ok"] += 1
        cands.append(d)
    by_t = {t: Counter(d["main_colors"] for d in cands if bucket(d) >= t - 1e-9) for t in args.thresholds}
    threshold = next((t for t in args.thresholds if all(by_t[t][x] >= args.shortlist_per_pair for x in pairs)),
                     args.thresholds[-1])
    cands = [d for d in cands if bucket(d) >= threshold - 1e-9]
    funnel[f"drafter bucket >= {threshold:.2f}"] = len(cands)
    print(f"{n_drafts} drafts; {dict(funnel)}")
    for t in args.thresholds:
        print(f"bucket >= {t:.2f}: " + " ".join(f"{x} {by_t[t][x]}" for x in pairs))

    shortlist = []
    for x in pairs:
        pair = sorted((d for d in cands if d["main_colors"] == x), key=lambda d: (-bucket(d), -d["mana_score"], tie(d)))
        shortlist += pair[:args.shortlist_per_pair]

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    cache_path = out / "review_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    old = Path(args.current) / "review_cache.json"
    old_cache = json.loads(old.read_text()) if old.exists() else {}
    todo = []
    for d in shortlist:
        d["_prompt"] = rd.prompt(d, d["stats"], texts)
        d["_key"] = hashlib.sha256((rd.SYSTEM_SHA + args.model + args.effort + d["_prompt"]).encode()).hexdigest()[:16]
        if d["_key"] not in cache and old_cache.get(d["_key"], {}).get("review"):
            cache[d["_key"]] = {**old_cache[d["_key"]], "from": "17lands-good/review_cache.json", "cost_usd": 0.0}
        if not cache.get(d["_key"], {}).get("review"):
            todo.append(d)
    if todo and not args.no_review:
        with ThreadPoolExecutor(args.parallel) as ex:
            for i, (key, how) in enumerate(ex.map(lambda d: rd.review(d["_key"], d["_prompt"], args, cache), todo)):
                print(f"{todo[i]['draft_id']} {todo[i]['main_colors']}: {how}", flush=True)
                cache_path.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    cache_path.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    missing = [d for d in shortlist if not cache.get(d["_key"], {}).get("review")]
    if missing:
        print(f"{len(missing)} shortlisted decks have no review; nothing written")
        return
    cost = sum(cache[d["_key"]].get("cost_usd", 0.0) for d in shortlist)

    for d in shortlist:
        d["review"] = cache[d["_key"]]["review"]
        flags = rd.red_flags(d, d["stats"], 0.53)
        d["stats"]["red_flags"] = [f for f in flags if not f.startswith("weak archetype")]
        d["archetype_flag"] = next((f for f in flags if f.startswith("weak archetype")), None)
        d["tier"] = 2 if d["review"]["rating"] >= args.min_rating and not d["stats"]["red_flags"] else 1
        d["deck_score_gih"] = round(sum(n * gih[c]["wr"] for c, n in d["deck"].items() if not gih[c]["land"])
                                    / sum(n for c, n in d["deck"].items() if not gih[c]["land"]), 5)
    order = lambda d: (-d["tier"], -d["review"]["rating"], -d["mana_score"], -bucket(d), tie(d))
    kept = []
    for x in pairs:
        kept += sorted((d for d in shortlist if d["main_colors"] == x and d["review"]["rating"] >= args.keep_rating),
                       key=order)[:args.per_pair]
    kept.sort(key=order)

    for f in out.glob("good_*.dck"):
        f.unlink()
    current = json.loads((Path(args.current) / "manifest.json").read_text())["decks"]
    cur_ids = {c["draft_id"]: c["file"] for c in current}
    decks = []
    for k, d in enumerate(kept):
        name = f"good_{k:02d}"
        arch = d["review"]["archetype"].strip()
        arch = re.sub(r"^[WUBRGwubrg]{2,5}(\+[WUBRGwubrg])?\s+", "", arch)  # the reviewer's own colour prefix
        colors = d["main_colors"] + (f"+{d['splash_colors'].lower()}" if d["splash_colors"] else "")
        title = f"{'★★' if d['tier'] == 2 else '★'} {name} · {colors} {arch} · review {d['review']['rating']}/5"
        lines = [f"NAME:{title}"] + [f"{n} [{numbers[c] if ':' in numbers[c] else 'DSK:' + numbers[c]}] {c}"
                                     for c, n in sorted(d["deck"].items(), key=lambda kv: (-kv[1], kv[0]))]
        (out / f"{name}.dck").write_text("\n".join(lines) + "\n")
        decks.append({"file": f"{name}.dck", "rank": k, "playmat_name": title, "tier": d["tier"],
                      **{x: d[x] for x in ("draft_id", "build_index", "build_games", "build_wins", "games", "wins", "losses",
                                           "main_colors", "splash_colors", "user_win_rate_bucket", "user_n_games_bucket")},
                      "drafter_bucket": round(bucket(d), 2), "rank_17lands": d["rank"], "review": d["review"], "mana_score": d["mana_score"], "mana": d["mana"],
                      "stats": d["stats"], "archetype_flag": d["archetype_flag"], "deck_score_gih": d["deck_score_gih"],
                      "in_current_pool": cur_ids.get(d["draft_id"]), "deck": d["deck"]})
    rated = Counter((d["main_colors"], d["review"]["rating"]) for d in shortlist)
    summary = {
        "source": Path(args.data).name, "drafts": n_drafts, "skipped": skipped, "funnel": dict(funnel),
        "candidates_by_threshold": {f"{t:.2f}": {x: by_t[t][x] for x in PAIRS} for t in args.thresholds},
        "threshold": threshold, "min_user_games": args.min_user_games, "min_build_games": args.min_build_games, "min_creatures": args.min_creatures,
        "shortlist_per_pair": args.shortlist_per_pair, "per_pair": args.per_pair, "keep_rating": args.keep_rating,
        "tier2": f"rating >= {args.min_rating} and no build red flag (weak-archetype flag excluded, see archetype_flag)",
        "reviewer": {"model": args.model, "effort": args.effort, "system_sha": rd.SYSTEM_SHA, "reviewed": len(shortlist),
                     "cost_usd": round(cost, 3)},
        "shortlist_ratings": {x: {r: rated[(x, r)] for r in range(1, 6) if rated[(x, r)]} for x in PAIRS},
        "kept": len(decks), "kept_by_pair": {x: sum(d["main_colors"] == x for d in decks) for x in PAIRS},
        "tiers": dict(Counter(d["tier"] for d in decks)),
        "overlap_with_current": {"draft_ids": sorted(set(cur_ids) & {d["draft_id"] for d in decks}),
                                 "shortlisted": len(set(cur_ids) & {d["draft_id"] for d in shortlist})},
        "decks": decks}
    (out / "manifest.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n")
    print(f"threshold {threshold}; reviewed {len(shortlist)} (cost ${cost:.2f}); kept {len(decks)} {summary['kept_by_pair']}; "
          f"tiers {summary['tiers']}; overlap {summary['overlap_with_current']}")
    print("shortlist ratings:", summary["shortlist_ratings"])


if __name__ == "__main__":
    main()
