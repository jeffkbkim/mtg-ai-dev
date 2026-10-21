"""Build a pool of real drafted DSK decks from 17lands' public game data, as XMage .dck files.

  python3 play/deck_pool.py <game_data_public.DSK.PremierDraft.csv.gz> <xmage numbers .tsv> <out dir> [--n 20] [--seed 7]

Each draft's deck is its most-played build (17lands logs the main deck of every game). Two kinds:
- typical: drafts sampled uniformly, so archetypes appear as often as people draft them;
- trophy: drafts that reached 7 wins (at most 2 losses).
Only 40-card decks whose every card is in XMage's DSK set are kept; decks with other cards (e.g. Special Guests) are
skipped and counted, never patched. The numbers file maps names to XMage collector numbers ("number<TAB>name").
Writes <out>/<kind>_<nn>.dck and <out>/manifest.json (draft id, record, colors, rank, card counts per deck).
"""
import argparse, csv, gzip, json, random
from collections import Counter, defaultdict
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("data"); p.add_argument("numbers"); p.add_argument("out")
p.add_argument("--n", type=int, default=20); p.add_argument("--seed", type=int, default=7)
args = p.parse_args()

numbers = {}
for line in Path(args.numbers).read_text().splitlines():
    num, name = line.split("\t", 1)
    numbers[name] = num

drafts = {}  # draft_id -> info
builds = defaultdict(dict)  # draft_id -> build_index -> [deck, games]
with gzip.open(args.data, "rt", newline="") as f:
    r = csv.reader(f)
    head = next(r)
    col = {h: i for i, h in enumerate(head)}
    deck_cols = [(i, h[5:]) for i, h in enumerate(head) if h.startswith("deck_")]
    for row in r:
        d, b = row[col["draft_id"]], row[col["build_index"]]
        info = drafts.get(d)
        if info is None:
            info = drafts[d] = {"draft_id": d, "games": 0, "wins": 0, "rank": row[col["rank"]],
                                "user_win_rate_bucket": row[col["user_game_win_rate_bucket"]]}
        info["games"] += 1
        info["wins"] += row[col["won"]] == "True"
        info["main_colors"], info["splash_colors"] = row[col["main_colors"]], row[col["splash_colors"]]
        bd = builds[d].get(b)
        if bd is None:
            deck = {name: int(row[i]) for i, name in deck_cols if row[i] not in ("0", "")}
            bd = builds[d][b] = [deck, 0]
        bd[1] += 1

skipped = Counter()
unsupported = Counter()
ok = []
for d, info in drafts.items():
    b, (deck, n) = max(builds[d].items(), key=lambda kv: kv[1][1])
    if sum(deck.values()) != 40:
        skipped["not 40 cards"] += 1
        continue
    missing = [c for c in deck if c not in numbers]
    if missing:
        skipped["card not in XMage DSK"] += 1
        unsupported.update(missing)
        continue
    info.update(build_index=b, build_games=n, losses=info["games"] - info["wins"], deck=deck)
    ok.append(info)

rng = random.Random(args.seed)
typical = rng.sample([i for i in ok if i["games"] >= 3], args.n)  # played at least 3 games with it
trophy = rng.sample([i for i in ok if i["wins"] >= 7 and i["losses"] <= 2 and i not in typical], args.n)

out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
manifest = []
for kind, picked in (("typical", typical), ("trophy", trophy)):
    for k, info in enumerate(picked):
        name = f"{kind}_{k:02d}"
        lines = [f"NAME:{name} (17lands DSK draft {info['draft_id']}, {info['wins']}-{info['losses']}, {info['main_colors']})"]
        lines += [f"{n} [DSK:{numbers[c]}] {c}" for c, n in sorted(info["deck"].items(), key=lambda kv: (-kv[1], kv[0]))]
        (out / f"{name}.dck").write_text("\n".join(lines) + "\n")
        manifest.append({"file": f"{name}.dck", "kind": kind, **{k2: info[k2] for k2 in (
            "draft_id", "build_index", "build_games", "games", "wins", "losses", "main_colors", "splash_colors",
            "rank", "user_win_rate_bucket")}, "deck": info["deck"]})
(out / "manifest.json").write_text(json.dumps({
    "source": Path(args.data).name, "seed": args.seed, "drafts": len(drafts), "eligible": len(ok),
    "skipped": dict(skipped), "unsupported_cards": dict(unsupported.most_common()), "decks": manifest}, indent=1))
print(f"{len(drafts)} drafts, {len(ok)} eligible, skipped {dict(skipped)}; unsupported cards: {unsupported.most_common(10)}")
print(f"typical colors: {Counter(i['main_colors'] for i in typical).most_common()}")
print(f"trophy colors: {Counter(i['main_colors'] for i in trophy).most_common()}")
