"""Re-review a pool's manifest-dread decks with the body count (review_decks.deck_stats: token makers, manifest dread
and creature recursion count as bodies, Jeff 2026-10-25), and update their review and tier in the manifest.

  python3 play/rereview_bodies.py <pool dir> [--model claude-opus-5-5] [--effort medium] [--parallel 5] [--dry-run]

Decks picked: the earlier review mentions manifest (archetype, verdict or concerns). Same reviewer, system prompt and
prompt builder as review_decks.py, so ratings compare. Tier (when the pool has tiers): 2 = rating >= 4 and no build
red flag (the weak-archetype flag excluded, as good_deck_pool_v2.py), else 1. The old review is kept as "review_before".
"""
import argparse, hashlib, json, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_decks as rd  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("pool"); p.add_argument("--model", default="claude-opus-5-5"); p.add_argument("--effort", default="medium")
    p.add_argument("--parallel", type=int, default=5); p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    pool = Path(args.pool)
    man = json.loads((pool / "manifest.json").read_text())
    texts = rd.load_card_text()
    cr = json.loads((rd.RATINGS / "dsk_color_ratings.json").read_text())
    color_wr = {r["short_name"]: r["wins"] / r["games"] for r in cr if not r["is_summary"] and r["games"]}
    cache_path = pool / "review_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    picked = [d for d in man["decks"] if d.get("review") and "manifest" in json.dumps(d["review"]).lower()]
    for d in picked:
        d["_stats"] = rd.deck_stats(d, texts, color_wr)
        d["_prompt"] = rd.prompt(d, d["_stats"], texts)
        d["_key"] = hashlib.sha256((rd.SYSTEM_SHA + args.model + args.effort + d["_prompt"]).encode()).hexdigest()[:16]
    todo = [d for d in picked if not cache.get(d["_key"], {}).get("review")]
    print(f"{pool.name}: {len(picked)} manifest decks, {len(todo)} to review")
    if args.dry_run:
        return
    with ThreadPoolExecutor(args.parallel) as ex:
        for d, (_, how) in zip(todo, ex.map(lambda d: rd.review(d["_key"], d["_prompt"], args, cache), todo)):
            print(d["file"], how, flush=True)
            cache_path.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    changes = []
    for d in picked:
        new = cache[d["_key"]].get("review")
        if not new:
            continue
        old = d["review"]
        d.setdefault("review_before", old)
        d["review"] = new
        s = d.pop("_stats")
        d.setdefault("stats", {}).update({k: s[k] for k in ("creatures", "bodies", "body_makers")})
        if "tier" in d:
            flags = [f for f in rd.red_flags(d, s, 0.53) if not f.startswith("weak archetype")]
            tier = 2 if new["rating"] >= 4 and not flags else 1
            if tier != d["tier"]:
                changes.append(f"{d['file']} tier {d['tier']} -> {tier}")
            d["tier"] = tier
        if new["rating"] != old["rating"]:
            changes.append(f"{d['file']} {d['main_colors']} {old['rating']} -> {new['rating']} ({new['archetype']})")
        for k in ("_prompt", "_key"):
            d.pop(k, None)
    for d in man["decks"]:
        for k in ("_prompt", "_key", "_stats"):
            d.pop(k, None)
    (pool / "manifest.json").write_text(json.dumps(man, indent=1, ensure_ascii=False) + "\n")
    print("\n".join(changes) or "no rating changes")


if __name__ == "__main__":
    main()
