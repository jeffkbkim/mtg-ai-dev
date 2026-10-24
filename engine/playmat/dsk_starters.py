"""Adds our real drafted DSK decks to a Playmat checkout's starter decks, so they can be picked to play and the AI is dealt
one (the patched client deals the Claude AI a dsk-good-* starter, other AIs any dsk-* starter).

  python3 engine/playmat/dsk_starters.py <playmat checkout>

Two pools: engine/xmage/decks/17lands-good (70 strong decks, files dsk-good-NN.dck) and engine/xmage/decks/17lands-r2
(160 decks, dsk-typical_NN / dsk-trophy_NN). Each deck's menu name carries its deck score (mean 17lands GIH WR of its
nonland cards, from 17lands-good/gih_wr.json), colors, record and rank, e.g. "★ good_00 · 58.6% · WUG · 7-2 Plat" or
"trophy_00 · 55.4% · UB · 7-2 Plat"; the good pool's names start with ★, or ★★ for its top tier (manifest "tier": 2,
see 17lands-good/REVIEW.md). Decks of either pool that break the colour rule (two_colors(): two main colors, at most a
light splash) are not listed at all. A good-pool deck the review rated 2 or lower has no star and the file
dsk-goodx-NN.dck: "Good only" hides it and the Claude AI isn't dealt it (both look for dsk-good-*). index.json lists ours strongest first, then
Playmat's own starters. The cover card is the deck's first nonland card.
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


RANKS = {"bronze": "Bronze", "silver": "Silver", "gold": "Gold", "platinum": "Plat", "diamond": "Diamond", "mythic": "Mythic"}


def two_colors(m, texts):
    """Jeff's colour rule (2026-10-23/24), for every deck we list: exactly two main colors and at most a light splash of
    a third (one splash color, in at most 3 nonland cards, with at least 3 lands that make it). Never 4 or 5 colors."""
    splash = m.get("splash_colors", "")
    if len(m["main_colors"]) != 2 or len(splash) > 1:
        return False
    if not splash:
        return True
    cards = sources = 0
    for name, n in m["deck"].items():
        c = texts[name]
        if "Land" in c["types"]:
            text = " ".join(c["rules"])
            if BASICS.get(name) == splash or f"{{{splash}}}" in text or "any color" in text or "basic land" in text.lower():
                sources += n
        elif f"{{{splash}}}" in c["cost"] + "".join(c[h]["cost"] for h in ("left", "right") if h in c):
            cards += n
    return cards <= 3 and sources >= 3


def playable(m, texts):
    """A good-pool deck worth its star and dealt to the Claude AI: the colour rule, and not rated 2 or lower by the
    review (greedy mana or too few creatures)."""
    rating = m.get("review", {}).get("rating")
    return two_colors(m, texts) and (rating is None or rating > 2)


BASICS = {"Plains": "W", "Island": "U", "Swamp": "B", "Mountain": "R", "Forest": "G"}


def main():
    playmat = Path(sys.argv[1])
    decks = ROOT / "engine/xmage/decks"
    gih = json.loads((decks / "17lands-good/gih_wr.json").read_text())
    texts = {c["name"]: c for c in json.loads((ROOT / "engine/vocab/dsk_card_text.json").read_text())}
    out = playmat / "Mage.Web.Client/public/starter-decks"
    index = [e for e in json.loads((out / "index.json").read_text()) if not e["file"].startswith("dsk-")]
    ours, skipped = [], {}
    for pool, prefix, star in (("17lands-good", "dsk-good-", "★ "), ("17lands-r2", "dsk-", "")):
        manifest = {d["file"]: d for d in json.loads((decks / pool / "manifest.json").read_text())["decks"]}
        for deck in sorted((decks / pool).glob("*.dck")):
            m = manifest[deck.name]
            if not two_colors(m, texts):
                skipped[pool] = skipped.get(pool, 0) + 1  # not listed at all; the .dck stays in the repo
                continue
            good = star and playable(m, texts)
            text = deck.read_text()
            cards, cover, wr, nonland = 0, None, 0.0, 0
            for line in text.splitlines():
                c = re.match(r"(\d+) \[(\w+):(\w+)\] (.+)", line)
                if not c:
                    continue
                n, card = int(c.group(1)), c.group(4)
                cards += n
                if not gih[card]["land"]:
                    wr += n * gih[card]["wr"]; nonland += n
                    if cover is None:
                        cover = {"name": card, "setCode": c.group(2), "cardNumber": c.group(3)}
            score = wr / nonland
            rank = RANKS.get(m.get("rank", ""), "")
            colors = m["main_colors"] + (f"+{m['splash_colors']}" if m.get("splash_colors") else "")
            mark = ("★★ " if m.get("tier") == 2 else star) if good else ""  # tier 2: passed the deck review (17lands-good/REVIEW.md)
            name = f"{mark}{deck.stem} · {100 * score:.1f}% · {colors} · {m['wins']}-{m['losses']}" + (f" {rank}" if rank else "")
            file = (f"{prefix}{deck.stem.removeprefix('good_')}.dck" if good else f"dsk-goodx-{deck.stem.removeprefix('good_')}.dck") if star \
                else f"{prefix}{deck.stem}.dck"
            (out / file).write_text(f"NAME:{name}\n" + "\n".join(text.splitlines()[1:]) + "\n")
            ours.append(({"file": file, "name": name, "cards": cards, "cover": cover}, score))
    ours.sort(key=lambda e: -e[1])
    (out / "index.json").write_text(json.dumps([e for e, _ in ours] + index, indent=2, ensure_ascii=False) + "\n")
    print(f"{len(ours)} DSK decks added to {out}; left out by the colour rule: {skipped}")


if __name__ == "__main__":
    main()
