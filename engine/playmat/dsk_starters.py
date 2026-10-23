"""Adds our real drafted DSK decks to a Playmat checkout's starter decks, so they can be picked to play and the AI is dealt
one (the patched client deals the AI a dsk-* starter when there is one).

  python3 engine/playmat/dsk_starters.py <playmat checkout> [deck dir, default engine/xmage/decks/17lands-r2]

Copies each <name>.dck to Mage.Web.Client/public/starter-decks/dsk-<name>.dck and lists it in that folder's index.json
(Playmat's own starters stay, after ours). The deck's name in the menu is the .dck's NAME line without the draft id,
e.g. "DSK trophy_04 (7-1, WB)". The cover card is the deck's first nonland card.
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    playmat = Path(sys.argv[1])
    decks = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "engine/xmage/decks/17lands-r2"
    out = playmat / "Mage.Web.Client/public/starter-decks"
    index = [e for e in json.loads((out / "index.json").read_text()) if not e["file"].startswith("dsk-")]
    ours = []
    for deck in sorted(decks.glob("*.dck")):
        text = deck.read_text()
        first = text.splitlines()[0]
        m = re.match(r"NAME:(\S+) \(17lands DSK draft \S+, ([^)]*)\)", first)
        name = f"DSK {m.group(1)} ({m.group(2)})" if m else f"DSK {deck.stem}"
        cards, cover = 0, None
        for line in text.splitlines():
            c = re.match(r"(\d+) \[(\w+):(\w+)\] (.+)", line)
            if not c:
                continue
            cards += int(c.group(1))
            if cover is None and c.group(4) not in ("Plains", "Island", "Swamp", "Mountain", "Forest"):
                cover = {"name": c.group(4), "setCode": c.group(2), "cardNumber": c.group(3)}
        file = f"dsk-{deck.stem}.dck"
        (out / file).write_text(f"NAME:{name}\n" + "\n".join(text.splitlines()[1:]) + "\n")
        ours.append({"file": file, "name": name, "cards": cards, "cover": cover})
    (out / "index.json").write_text(json.dumps(ours + index, indent=2) + "\n")
    print(f"{len(ours)} DSK decks added to {out}")


if __name__ == "__main__":
    main()
