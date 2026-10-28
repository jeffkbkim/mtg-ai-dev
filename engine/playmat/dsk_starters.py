"""Adds our real drafted DSK and FDN decks to a Playmat checkout's starter decks, so they can be picked to play and the AI is dealt
one (the patched client deals the Claude AI a dsk-good-* starter, other AIs any dsk-* starter).

  python3 engine/playmat/dsk_starters.py <playmat checkout>

Listed pools: engine/xmage/decks/17lands-good-v2 (100 reviewed decks, 10 per colour pair, files dsk-good-v2-NN.dck),
engine/xmage/decks/17lands-r2 (160 decks, dsk-typical_NN / dsk-trophy_NN) and, for Foundations,
engine/xmage/decks/17lands-fdn-good (98 reviewed decks, files fdn-good-NN.dck, names "★★ fdn_08 · ..."). The first good pool (17lands-good, 70 decks)
is retired since 2026-10-25: not listed, but rated in strengths.json so saved copies of its decks still get a matched
opponent. A good-pool name gives its tier, the review's archetype and rating, e.g.
"★★ v2_08 · WU eerie enchantments/tempo · review 4/5" (★★: tier 2, the review's rating 4+); an older deck's name
gives its colors, e.g. "trophy_00 · UB". Records and deck scores stay in the manifests (Jeff 2026-10-24: misleading in
the menu). Decks of either pool that break the colour rule (two_colors(): two main colors, at most a light splash) are
not listed at all. A good-pool deck the review rated 2 or lower has no star and the file dsk-goodx-NN.dck: "Good only"
hides it and the Claude AI isn't dealt it (both look for dsk-good-*). index.json lists the starred decks by tier and
review rating, then the unstarred ones, then the older pool, steadier mana first and then the drafter's long-run win
rate. Playmat's own starters (60-card and Commander) are not listed. The cover card is the deck's first nonland card.
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


def deck_sig(text):
    """FNV-1a over "amount name" lines sorted by name, as the web client's deckSig (core/decks/deckStrength.ts), so a
    saved copy of a starter is recognised as that starter."""
    counts = {}
    for line in text.splitlines():
        c = re.match(r"(\d+) \[[^\]]*\] (.+)", line)
        if c:
            counts[c.group(2)] = counts.get(c.group(2), 0) + int(c.group(1))
    h = 0x811C9DC5
    for ch in "|".join(f"{n} {name}" for name, n in sorted(counts.items())):
        h = ((h ^ ord(ch)) * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


def main():
    playmat = Path(sys.argv[1])
    decks = ROOT / "engine/xmage/decks"
    # card text of every set we have decks of (DSK, FDN; no shared names but basics)
    texts = {c["name"]: c for s in ("dsk", "fdn") for c in json.loads((ROOT / f"engine/vocab/{s}_card_text.json").read_text())}
    out = playmat / "Mage.Web.Client/public/starter-decks"
    # Jeff 2026-10-24: only our DSK Limited decks are listed; Playmat's own 60-card and Commander starters are left out
    # (their files stay)
    index = []
    ours, skipped, known = [], {}, []
    # Jeff 2026-10-25: the v2 pool (10 per colour pair) is the starred pool; the first good pool is no longer listed
    # (retired: its files stay, and strengths.json still rates saved copies of its decks)
    # 2026-10-28: Foundations (FDN) too, its reviewed pool as fdn-good-NN (Jeff: add FDN alongside DSK); the web client
    # keeps each set's decks apart (deck set tabs, the AI's deck from the player's deck's set)
    for pool, prefix, star, listed, label in (("17lands-good-v2", "dsk-good-v2-", "★ ", True, "v2_"),
                                              ("17lands-good", "dsk-good-", "★ ", False, None),
                                              ("17lands-r2", "dsk-", "", True, None),
                                              ("17lands-fdn-good", "fdn-good-", "★ ", True, "fdn_")):
        manifest = {d["file"]: d for d in json.loads((decks / pool / "manifest.json").read_text())["decks"]}
        for deck in sorted((decks / pool).glob("*.dck")):
            m = manifest[deck.name]
            review = m.get("review")
            stem = f"{label}{deck.stem.removeprefix('good_')}" if label else deck.stem
            if review:  # every rated deck, listed or not, so a saved copy of a hidden one still gets a matched opponent
                known.append({"sig": deck_sig(deck.read_text()), "name": stem, "listed": listed and two_colors(m, texts),
                              "strength": {"tier": (m.get("tier") or 1) if star and playable(m, texts) else 0,
                                           "rating": review["rating"], "colors": m["main_colors"]}})
            if not listed:
                continue
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
            # Jeff 2026-10-24: no 7-X record or card-quality score in the name (misleading); they stay in the manifest
            if review:
                mark = ("★★ " if m.get("tier") == 2 else star) if good else ""  # tier 2: passed the deck review (REVIEW.md)
                arch = re.sub(r"\s*\([^)]*\)?", "", review["archetype"]).split(",")[0].strip()
                arch = arch if len(arch) <= 34 else arch[:34].rsplit(" ", 1)[0]
                name = f"{mark}{stem} · {arch} · review {review['rating']}/5"
            else:
                name = f"{stem} · {colors}"
            file = (f"{prefix}{deck.stem.removeprefix('good_')}.dck" if good else f"{prefix.replace('good', 'goodx')}{deck.stem.removeprefix('good_')}.dck") if star \
                else f"{prefix}{deck.stem}.dck"
            (out / file).write_text(f"NAME:{name}\n" + "\n".join(text.splitlines()[1:]) + "\n")
            # order: starred good decks by tier and review, then unstarred ones, then the older pool; within each, the
            # steadier mana first, then the drafter's long-run win rate
            group = 0 if good else 1 if star else 2
            key = (group, -(m.get("tier") or 0), -(review["rating"] if review else 0), consistency(m, texts),
                   -float(m.get("user_win_rate_bucket") or 0))
            # mtg-ai web client: the AI is dealt a deck of about the player's deck's strength (deckStrength.ts)
            strength = {"tier": (m.get("tier") or 1) if good else 0, "rating": review["rating"] if review else None,
                        "colors": m["main_colors"]}
            ours.append(({"file": file, "name": name, "cards": cards, "cover": cover, "strength": strength,
                          "sig": deck_sig(text)}, key))
    ours.sort(key=lambda e: e[1])
    (out / "strengths.json").write_text(json.dumps(known, indent=1, ensure_ascii=False) + "\n")
    (out / "index.json").write_text(json.dumps([e for e, _ in ours] + index, indent=2, ensure_ascii=False) + "\n")
    print(f"{len(ours)} DSK and FDN decks added to {out}; left out by the colour rule: {skipped}")


if __name__ == "__main__":
    main()
