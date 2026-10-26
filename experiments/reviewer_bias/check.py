"""Is the deck reviewer biased by colour pair? (read-only analysis)

  python3 experiments/reviewer_bias/check.py --parse-cache <parsed.json.gz>

Every deck the reviewer (play/review_decks.py, claude-opus-5-5 medium, the same system prompt) has rated, found by
rebuilding each candidate's prompt from the parsed 17lands drafts and looking it up in every review_cache.json under
engine/xmage/decks/. Per deck: rating, colour pair, card quality (mean GIH WR of its nonland cards over all games,
17lands-good/gih_wr.json), the drafter's long-run win-rate bucket and the pair's 17lands win rate. A least-squares fit
rating ~ card quality + drafter bucket (no pair term) gives each pair's mean residual: how much the reviewer rates that
pair's decks above or below what their card quality predicts. Records are not used (7-game samples are noise).
"""
import argparse, collections, gzip, hashlib, json, statistics, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "play"))
import review_decks as rd  # noqa: E402

# the ratings measured are the v1 reviewer's (every review so far), whatever REVIEW_SYSTEM says for a retest
V1_SHA = hashlib.sha256(rd.SYSTEMS["v1"].encode()).hexdigest()[:12]


TAGS = {"manifest": ["manifest"], "ramp": ["ramp"], "control": ["control"], "aggro": ["aggro"], "tempo": ["tempo"],
        "midrange": ["midrange"], "eerie/rooms": ["eerie", "room"], "delirium": ["delirium"], "survival": ["survival", "survivor"],
        "reanimator": ["reanimat", "recursion"]}


def by_tag(rows):
    out = collections.defaultdict(list)
    for r in rows:
        for t in r["tags"]:
            out[t].append(r)
    return out


def main():
    p = argparse.ArgumentParser(); p.add_argument("--parse-cache", required=True)
    p.add_argument("--retest", type=int, default=0, help="re-review this many UG/manifest and this many control decks with REVIEW_SYSTEM's prompt")
    p.add_argument("--parallel", type=int, default=5); p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--model", default="claude-opus-5-5"); p.add_argument("--effort", default="medium")
    args = p.parse_args()
    _, _, drafts = json.loads(gzip.decompress(Path(args.parse_cache).read_bytes()))
    cache = {}
    for f in (ROOT / "engine/xmage/decks").rglob("review_cache.json"):
        for k, v in json.loads(f.read_text()).items():
            if v.get("review"):
                cache[k] = v["review"]
    texts = rd.load_card_text()
    cr = json.loads((rd.RATINGS / "dsk_color_ratings.json").read_text())
    color_wr = {r["short_name"]: r["wins"] / r["games"] for r in cr if not r["is_summary"] and r["games"]}
    gih = json.loads((ROOT / "engine/xmage/decks/17lands-good/gih_wr.json").read_text())
    rows = []
    for d in drafts:
        if len(d["main_colors"]) != 2 or float(d["user_win_rate_bucket"] or 0) < 0.60:
            continue
        try:
            s = rd.deck_stats(d, texts, color_wr)
        except KeyError:
            continue
        # the prompt as built now (with the body count), and as built before it (2026-10-25)
        old = dict(s, body_makers=0)
        r = None
        for st in (s, old):
            key = hashlib.sha256((V1_SHA + args.model + args.effort + rd.prompt(d, st, texts)).encode()).hexdigest()[:16]
            r = r or cache.get(key)
        if not r:
            continue
        spells = [(n, gih[c]["wr"]) for c, n in d["deck"].items() if c in gih and not gih[c]["land"]]
        q = sum(n * w for n, w in spells) / sum(n for n, _ in spells)
        arch = (r.get("archetype", "") + " " + r.get("verdict", "")).lower()
        tags = [t for t, words in TAGS.items() if any(w in arch for w in words)]
        rows.append({"pair": d["main_colors"], "rating": r["rating"], "q": q, "b": float(d["user_win_rate_bucket"]), "tags": tags,
                     "concerns": r.get("concerns", []), "arch": r.get("archetype", ""), "d": d, "stats": s, "draft_id": d["draft_id"]})
    print(f"{len(rows)} rated decks found (of {len(cache)} cached reviews)")
    if args.retest:
        return retest(rows, args, texts)
    # least squares: rating = a + b1*q + b2*bucket
    n = len(rows)
    X = [(1.0, r["q"], r["b"]) for r in rows]; y = [r["rating"] for r in rows]
    XtX = [[sum(x[i] * x[j] for x in X) for j in range(3)] for i in range(3)]
    Xty = [sum(x[i] * t for x, t in zip(X, y)) for i in range(3)]
    # solve 3x3
    import copy
    A = copy.deepcopy(XtX); bvec = Xty[:]
    for i in range(3):
        piv = A[i][i]
        for j in range(i, 3): A[i][j] /= piv
        bvec[i] /= piv
        for k in range(3):
            if k != i:
                f = A[k][i]
                for j in range(i, 3): A[k][j] -= f * A[i][j]
                bvec[k] -= f * bvec[i]
    coef = bvec
    print(f"fit: rating = {coef[0]:.2f} + {coef[1]:.2f} x card quality + {coef[2]:.2f} x drafter bucket")
    by = collections.defaultdict(list)
    for r in rows:
        r["res"] = r["rating"] - (coef[0] + coef[1] * r["q"] + coef[2] * r["b"])
        by[r["pair"]].append(r)
    print("\n| pair | 17lands WR | decks | mean rating | % rated 4 | mean card quality | residual (rating vs quality) | top concerns |")
    print("|---|---|---|---|---|---|---|---|")
    for pair, rs in sorted(by.items(), key=lambda kv: -color_wr.get(kv[0], 0)):
        conc = collections.Counter(c for r in rs for c in r["concerns"]).most_common(3)
        sd = statistics.pstdev([r["res"] for r in rs]) / max(1, len(rs)) ** 0.5
        print(f"| {pair} | {100*color_wr.get(pair, 0):.1f} | {len(rs)} | {statistics.mean(r['rating'] for r in rs):.2f} | "
              f"{100*sum(r['rating'] >= 4 for r in rs)/len(rs):.0f} | {100*statistics.mean(r['q'] for r in rs):.2f} | "
              f"{statistics.mean(r['res'] for r in rs):+.2f} ± {sd:.2f} | {', '.join(f'{c} {k}' for c, k in conc)} |")
    print("\n| archetype tag | decks | mean rating | % rated 4 | residual | top concerns |\n|---|---|---|---|---|---|")
    for tag, rs in sorted(by_tag(rows).items(), key=lambda kv: statistics.mean(r['res'] for r in kv[1])):
        conc = collections.Counter(c for r in rs for c in r["concerns"]).most_common(3)
        sd = statistics.pstdev([r["res"] for r in rs]) / max(1, len(rs)) ** 0.5
        print(f"| {tag} | {len(rs)} | {statistics.mean(r['rating'] for r in rs):.2f} | {100*sum(r['rating'] >= 4 for r in rs)/len(rs):.0f} | "
              f"{statistics.mean(r['res'] for r in rs):+.2f} ± {sd:.2f} | {', '.join(f'{c} {k}' for c, k in conc)} |")
    ug = [r for r in rows if r["pair"] == "UG" or "manifest" in r["tags"]]
    print(f"\nUG/manifest decks ({len(ug)}): concerns", collections.Counter(c for r in ug for c in r["concerns"]).most_common(10))



def retest(rows, args, texts):
    """Re-review a test set with the reviewer prompt in REVIEW_SYSTEM (cache: review_cache_<sha>.json here): UG or
    manifest decks, and control decks of other pairs, both already rated; before and after per group."""
    from concurrent.futures import ThreadPoolExecutor
    key_of = lambda r: hashlib.sha256(r["draft_id"].encode()).hexdigest()
    seen, ug, ctrl = set(), [], []
    for r in sorted(rows, key=key_of):
        if r["draft_id"] in seen:
            continue
        seen.add(r["draft_id"])
        if r["pair"] == "UG" or "manifest" in r["tags"]:
            ug.append(r)
        elif "control" in r["tags"]:
            ctrl.append(r)
    test = ug[:args.retest] + ctrl[:args.retest]
    path = Path(__file__).parent / f"review_cache_{rd.SYSTEM_SHA}.json"
    cache = json.loads(path.read_text()) if path.exists() else {}
    for r in test:
        r["_prompt"] = rd.prompt(r["d"], r["stats"], texts)
        r["_key"] = hashlib.sha256((rd.SYSTEM_SHA + args.model + args.effort + r["_prompt"]).encode()).hexdigest()[:16]
    todo = [r for r in test if not cache.get(r["_key"], {}).get("review")]
    with ThreadPoolExecutor(args.parallel) as ex:
        for _ in ex.map(lambda r: rd.review(r["_key"], r["_prompt"], args, cache), todo):
            path.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    path.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    cost = sum(cache[r["_key"]].get("cost_usd", 0) for r in todo if r["_key"] in cache)
    print(f"system {rd.SYSTEM_SHA}: re-reviewed {len(todo)} (cost ${cost:.2f})")
    for name, group in (("UG/manifest", ug[:args.retest]), ("control, other pairs", ctrl[:args.retest])):
        new = [cache[r["_key"]]["review"]["rating"] for r in group if cache.get(r["_key"], {}).get("review")]
        old = [r["rating"] for r in group if cache.get(r["_key"], {}).get("review")]
        moves = collections.Counter(n - o for n, o in zip(new, old))
        print(f"{name}: {len(new)} decks, mean {statistics.mean(old):.2f} -> {statistics.mean(new):.2f}, "
              f"4/5: {sum(o >= 4 for o in old)} -> {sum(n >= 4 for n in new)}, changes {dict(sorted(moves.items()))}")


if __name__ == "__main__":
    main()
