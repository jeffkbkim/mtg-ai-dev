"""Adds our real drafted DSK decks to a Playmat checkout's starter decks, so they can be picked to play and the AI is dealt
one (the patched client deals the Claude AI a dsk-good-* starter, other AIs any dsk-* starter).

  python3 engine/playmat/dsk_starters.py <playmat checkout>

Two pools: engine/xmage/decks/17lands-good (70 reviewed decks, files dsk-good-NN.dck) and engine/xmage/decks/17lands-r2
(160 decks, dsk-typical_NN / dsk-trophy_NN). A good-pool name gives its tier, the review's archetype and rating, e.g.
"★★ good_08 · WU eerie enchantments/tempo · review 4/5" (★★: tier 2, see 17lands-good/REVIEW.md); an older deck's name
gives its colors, e.g. "trophy_00 · UB". Records and deck scores stay in the manifests (Jeff 2026-10-24: misleading in
the menu). Decks of either pool that break the colour rule (two_colors(): two main colors, at most a light splash) are
not listed at all. A good-pool deck the review rated 2 or lower has no star and the file dsk-goodx-NN.dck: "Good only"
hides it and the Claude AI isn't dealt it (both look for dsk-good-*). index.json lists the starred decks by tier and
review rating, then the unstarred ones, then the older pool, steadier mana first and then the drafter's long-run win
rate; Playmat's own starters follow. The cover card is the deck's first nonland card.
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def two_colors(m, texts):
    """Jeff's colour rule (2026-10-23/24), for every deck we list: exactly two main colors and at most a light splash of
    a third (one splash color, in at most 3 nonland cards, with at least 3 lands that make it). Never 4 or 5 colors."""
    splash = m.get("splash_colors", "")
    if len(m["main_colors"]) != 2 or len(splash) > 1:
        return False
    if not splash:
        return True
    return color_cards(m, texts, splash) <= 3 and sources(m, texts, splash) >= 3


def sources(m, texts, color):
    """Lands in the deck that make this color (basics, duals, fetches of basics, any-color lands)."""
    n = 0
    for name, k in m["deck"].items():
        c = texts[name]
        if "Land" in c["types"]:
            text = " ".join(c["rules"])
            if BASICS.get(name) == color or f"{{{color}}}" in text or "any color" in text or "basic land" in text.lower():
                n += k
    return n


def color_cards(m, texts, color):
    """Nonland cards whose cost (either door, for a Room) has this color."""
    return sum(k for name, k in m["deck"].items() if "Land" not in texts[name]["types"]
               and f"{{{color}}}" in texts[name]["cost"] + "".join(texts[name][h]["cost"] for h in ("left", "right") if h in texts[name]))


def consistency(m, texts):
    """Sort key for mana, best first: no splash before a splash, then the fewest sources of a main color (more is better)."""
    return (len(m.get("splash_colors", "")), -min(sources(m, texts, c) for c in m["main_colors"]))


def playable(m, texts):
    """A good-pool deck worth its star and dealt to the Claude AI: the colour rule, and not rated 2 or lower by the
    review (greedy mana or too few creatures)."""
    rating = m.get("review", {}).get("rating")
    return two_colors(m, texts) and (rating is None or rating > 2)


BASICS = {"Plains": "W", "Island": "U", "Swamp": "B", "Mountain": "R", "Forest": "G"}


def main():
    playmat = Path(sys.argv[1])
    decks = ROOT / "engine/xmage/decks"
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
            cards, cover = 0, None
            for line in text.splitlines():
                c = re.match(r"(\d+) \[(\w+):(\w+)\] (.+)", line)
                if not c:
                    continue
                cards += int(c.group(1))
                if cover is None and "Land" not in texts[c.group(4)]["types"]:
                    cover = {"name": c.group(4), "setCode": c.group(2), "cardNumber": c.group(3)}
            colors = m["main_colors"] + (f"+{m['splash_colors']}" if m.get("splash_colors") else "")
            review = m.get("review")
            # Jeff 2026-10-24: no 7-X record or card-quality score in the name (misleading); they stay in the manifest
            if review:
                mark = ("★★ " if m.get("tier") == 2 else star) if good else ""  # tier 2: passed the deck review (REVIEW.md)
                arch = re.sub(r"\s*\([^)]*\)?", "", review["archetype"]).split(",")[0].strip()
                arch = arch if len(arch) <= 34 else arch[:34].rsplit(" ", 1)[0]
                name = f"{mark}{deck.stem} · {arch} · review {review['rating']}/5"
            else:
                name = f"{deck.stem} · {colors}"
            file = (f"{prefix}{deck.stem.removeprefix('good_')}.dck" if good else f"dsk-goodx-{deck.stem.removeprefix('good_')}.dck") if star \
                else f"{prefix}{deck.stem}.dck"
            (out / file).write_text(f"NAME:{name}\n" + "\n".join(text.splitlines()[1:]) + "\n")
            # order: starred good decks by tier and review, then unstarred ones, then the older pool; within each, the
            # steadier mana first, then the drafter's long-run win rate
            group = 0 if good else 1 if star else 2
            key = (group, -(m.get("tier") or 0), -(review["rating"] if review else 0), consistency(m, texts),
                   -float(m.get("user_win_rate_bucket") or 0))
            ours.append(({"file": file, "name": name, "cards": cards, "cover": cover}, key))
    ours.sort(key=lambda e: e[1])
    (out / "index.json").write_text(json.dumps([e for e, _ in ours] + index, indent=2, ensure_ascii=False) + "\n")
    print(f"{len(ours)} DSK decks added to {out}; left out by the colour rule: {skipped}")


if __name__ == "__main__":
    main()
