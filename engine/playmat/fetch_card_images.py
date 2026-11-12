"""Caches DSK and FDN card pictures on the Mac mini, so Playmat's pages don't depend on Scryfall being up (2026-11-12:
Scryfall's picture server refused connections for hours). Pictures come from Wizards' Gatherer (the og:image of each
card's page), one request at a time with a pause; files that already exist are skipped, so a rerun only fills gaps.

  python3 engine/playmat/fetch_card_images.py [--out ~/mtg-data/card-images] [--sets DSK FDN]

Writes <out>/<set>/<collector number>.webp and <out>/index.json (the "set/number" keys that exist, which the web client
reads to know what it can serve locally).
"""
import argparse, json, re, time, urllib.error, urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
AGENT = {"User-Agent": "Mozilla/5.0 (mtg-ai card cache)"}


def get(url, tries=3):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=AGENT), timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 404, b""
        except Exception:
            pass
        time.sleep(2 * 2 ** attempt)
    return 0, b""


def slugs(name):
    front = name.split(" // ")[0]
    base = front.lower().replace("'", "").replace("’", "")
    one = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    two = re.sub(r"[^a-z0-9]+", "-", front.lower()).strip("-")
    return list(dict.fromkeys([one, two]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path.home() / "mtg-data" / "card-images")
    ap.add_argument("--sets", nargs="+", default=["DSK", "FDN"])
    ap.add_argument("--pause", type=float, default=0.5)
    a = ap.parse_args()
    missing = []
    for s in a.sets:
        folder = a.out / s.lower()
        folder.mkdir(parents=True, exist_ok=True)
        for line in (ROOT / "engine" / "vocab" / f"{s.lower()}_numbers.tsv").read_text().splitlines():
            number, name = line.split("\t", 1)
            card_set = s
            if ":" in number:  # a card from another set in this one's packs (FDN's Special Guests: "SPG:80")
                card_set, number = number.split(":", 1)
            target = a.out / card_set.lower() / f"{number}.webp"
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                continue
            image = None
            for slug in slugs(name):
                code, page = get(f"https://gatherer.wizards.com/{card_set}/en-us/{number}/{slug}")
                time.sleep(a.pause)
                m = re.search(rb'og:image" content="([^"]+)"', page) if code == 200 else None
                if m:
                    image = m.group(1).decode()
                    break
                if code == 200:  # some pages have no og:image: the picture named most often next to the card's name
                    text = page.decode("utf8", "ignore")
                    near = Counter(h for k in re.finditer(re.escape(name.split(" // ")[0]), text)
                                   for h in re.findall(r"Cards/medium/([0-9A-F]{64})", text[max(0, k.start() - 600):k.start() + 600]))
                    if near:
                        image = f"https://gatherer-static.wizards.com/Cards/medium/{near.most_common(1)[0][0]}.webp"
                        break
            if not image:
                missing.append(f"{card_set} {number} {name}")
                continue
            code, data = get(image)
            time.sleep(a.pause)
            if code == 200 and data:
                target.write_bytes(data)
            else:
                missing.append(f"{card_set} {number} {name} (image)")
    keys = sorted(f"{p.parent.name}/{p.stem}" for p in a.out.glob("*/*.webp"))
    (a.out / "index.json").write_text(json.dumps(keys))
    print(f"{len(keys)} pictures cached; missing {len(missing)}")
    for m in missing:
        print("  missing", m)


if __name__ == "__main__":
    main()
