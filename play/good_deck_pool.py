"""Build a pool of strong real DSK decks from 17lands' public game data, as XMage .dck files.

  python3 play/good_deck_pool.py <game_data_public.DSK.PremierDraft.csv.gz> <xmage numbers .tsv> <17lands cards.csv> <out dir>
      [--n 70] [--min-eligible 80] [--thresholds 0.60 0.58 0.56 0.54] [--compare <earlier manifest.json> ...]

Eligibility is deck_pool.py's: a draft's deck is its most-played build, 40 cards, every card in the numbers file;
decks with other cards are skipped and counted, never patched. Candidates are trophy drafts (7 wins, at most 2
losses) whose drafter's user_game_win_rate_bucket is at least the first threshold that leaves --min-eligible decks.
Deck score = mean GIH WR over the deck's nonland cards, weighted by copies. A card's GIH WR comes from every game
row in the file: the card was in hand if it was in the opening hand or drawn (opening_hand_/drawn_ > 0), and its
win rate is wins/games over those games. Lands are cards whose cards.csv type line has "Land" before any " - ".
The top --n by score are written as <out>/good_<nn>.dck (00 best), with <out>/manifest.json and <out>/gih_wr.json.
--compare manifests are not excluded, only counted as draft_id overlap.
"""
import argparse, csv, gzip, json
from collections import Counter, defaultdict
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("data"); p.add_argument("numbers"); p.add_argument("cards"); p.add_argument("out")
p.add_argument("--n", type=int, default=70); p.add_argument("--min-eligible", type=int, default=80)
p.add_argument("--thresholds", type=float, nargs="+", default=[0.60, 0.58, 0.56, 0.54])
p.add_argument("--compare", nargs="*", default=[])
args = p.parse_args()

numbers = {}
for line in Path(args.numbers).read_text().splitlines():
    num, name = line.split("\t", 1)
    numbers[name] = num
types = {}
with open(args.cards, newline="") as f:
    for c in csv.DictReader(f):
        if c["expansion"] == "DSK" or c["name"] not in types:
            types[c["name"]] = c["types"]
is_land = lambda c: "Land" in types[c].split(" - ")[0].split()

drafts = {}  # draft_id -> info
builds = defaultdict(dict)  # draft_id -> build_index -> [deck, games]
gih = defaultdict(lambda: [0, 0])  # card -> [games in hand, wins]
with gzip.open(args.data, "rt", newline="") as f:
    r = csv.reader(f)
    head = next(r)
    col = {h: i for i, h in enumerate(head)}
    deck_cols = [(i, h[5:]) for i, h in enumerate(head) if h.startswith("deck_")]
    hand_cols = [(col["opening_hand_" + c], col["drawn_" + c], c) for _, c in deck_cols]
    for row in r:
        d, b = row[col["draft_id"]], row[col["build_index"]]
        won = row[col["won"]] == "True"
        for i, j, c in hand_cols:
            if row[i] not in ("0", "") or row[j] not in ("0", ""):
                g = gih[c]; g[0] += 1; g[1] += won
        info = drafts.get(d)
        if info is None:
            info = drafts[d] = {"draft_id": d, "games": 0, "wins": 0, "rank": row[col["rank"]],
                                "user_win_rate_bucket": row[col["user_game_win_rate_bucket"]]}
        info["games"] += 1
        info["wins"] += won
        info["main_colors"], info["splash_colors"] = row[col["main_colors"]], row[col["splash_colors"]]
        bd = builds[d].get(b)
        if bd is None:
            deck = {name: int(row[i]) for i, name in deck_cols if row[i] not in ("0", "")}
            bd = builds[d][b] = [deck, 0]
        bd[1] += 1
gih_wr = {c: {"games": g, "wins": w, "wr": w / g} for c, (g, w) in sorted(gih.items())}

skipped = Counter()
unsupported = Counter()
no_type = set()
trophies = []
for d, info in drafts.items():
    if not (info["wins"] >= 7 and info["games"] - info["wins"] <= 2):
        continue
    b, (deck, n) = max(builds[d].items(), key=lambda kv: kv[1][1])
    if sum(deck.values()) != 40:
        skipped["not 40 cards"] += 1
        continue
    missing = [c for c in deck if c not in numbers]
    if missing:
        skipped["card not in XMage DSK"] += 1
        unsupported.update(missing)
        continue
    no_type.update(c for c in deck if c not in types)
    spells = {c: k for c, k in deck.items() if c in types and not is_land(c)}
    score = sum(k * gih_wr[c]["wr"] for c, k in spells.items()) / sum(spells.values())
    info.update(build_index=b, build_games=n, losses=info["games"] - info["wins"], deck=deck, score=score,
                nonland_cards=sum(spells.values()))
    trophies.append(info)
assert not no_type, f"cards missing from cards.csv: {sorted(no_type)}"

bucket = lambda i: float(i["user_win_rate_bucket"] or "nan")
eligible = {t: sum(bucket(i) >= t for i in trophies) for t in args.thresholds}
threshold = next((t for t in args.thresholds if eligible[t] >= args.min_eligible), args.thresholds[-1])
picked = sorted((i for i in trophies if bucket(i) >= threshold), key=lambda i: -i["score"])[:args.n]

RANK = {"bronze": "Bronze", "silver": "Silver", "gold": "Gold", "platinum": "Plat", "diamond": "Diamond", "mythic": "Mythic"}
out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
manifest = []
for k, info in enumerate(picked):
    name = f"good_{k:02d}"
    tag = [name, f"{info['wins']}-{info['losses']}", RANK.get(info["rank"], ""),
           f"drafter {100 * bucket(info):.0f}%", f"deck {100 * info['score']:.1f}%", info["main_colors"]]
    lines = ["NAME:" + " · ".join(t for t in tag if t)]
    # numbers are DSK collector numbers, or "SPG:<n>" for a Special Guest
    lines += [f"{n} [{numbers[c] if ':' in numbers[c] else 'DSK:' + numbers[c]}] {c}" for c, n in sorted(info["deck"].items(), key=lambda kv: (-kv[1], kv[0]))]
    (out / f"{name}.dck").write_text("\n".join(lines) + "\n")
    manifest.append({"file": f"{name}.dck", "rank_by_score": k, "deck_score": round(info["score"], 5), **{k2: info[k2] for k2 in (
        "draft_id", "build_index", "build_games", "games", "wins", "losses", "main_colors", "splash_colors",
        "rank", "user_win_rate_bucket", "nonland_cards")}, "deck": info["deck"]})
overlap = {m: len({d["draft_id"] for d in json.loads(Path(m).read_text())["decks"]} & {i["draft_id"] for i in picked})
           for m in args.compare}
(out / "manifest.json").write_text(json.dumps({
    "source": Path(args.data).name, "drafts": len(drafts), "trophy_drafts": sum(1 for i in drafts.values()
        if i["wins"] >= 7 and i["games"] - i["wins"] <= 2), "trophy_eligible": len(trophies),
    "skipped": dict(skipped), "unsupported_cards": dict(unsupported.most_common()),
    "eligible_by_drafter_bucket": {f"{t:.2f}": eligible[t] for t in args.thresholds}, "threshold": threshold,
    "min_eligible": args.min_eligible, "kept": len(picked),
    "deck_score": "mean GIH WR over nonland cards weighted by copies; GIH from all game rows (opening_hand_ or drawn_ > 0)",
    "gih_games": sum(i["games"] for i in drafts.values()), "overlap_by_draft_id": overlap, "decks": manifest}, indent=1))
for c, v in gih_wr.items():
    v["land"] = c in types and is_land(c)  # deck scores leave lands out (engine/playmat/dsk_starters.py reads this)
(out / "gih_wr.json").write_text(json.dumps(gih_wr, indent=1))
print(f"{len(drafts)} drafts, {len(trophies)} eligible trophies, skipped {dict(skipped)}; unsupported: {unsupported.most_common(5)}")
print(f"eligible by drafter bucket: {eligible}; threshold {threshold}; kept {len(picked)}")
print(f"scores {picked[0]['score']:.4f} .. {picked[-1]['score']:.4f}; colors {Counter(i['main_colors'] for i in picked).most_common()}")
print(f"overlap: {overlap}")
