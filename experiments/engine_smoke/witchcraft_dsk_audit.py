"""Audit parser/bridge omissions; this does NOT establish runtime correctness.

Requires the pinned Witchcraft checkout, Lark and its bundled oracle corpus.
Use an XMage DSK set-registration Java file to select names, not an Arena-pool claim.
"""
import argparse
import collections
import json
import os
from pathlib import Path
import re
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("witchcraft", type=Path)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("dsk_registration", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.witchcraft.resolve()
    names = set(re.findall(r'new SetCardInfo\("([^"]+)",', args.dsk_registration.read_text()))
    names.update(face for name in list(names) for face in name.split(" // "))
    cards = [c for c in json.loads(args.corpus.read_text()) if c["name"] in names]
    with tempfile.TemporaryDirectory(prefix="witchcraft-dsk-") as temporary:
        temporary = Path(temporary)
        subset = temporary / "corpus.json"
        subset.write_text(json.dumps(cards))
        os.environ["MTG_CORPUS"] = str(subset)
        os.environ["CARD_JOBS"] = "1"
        sys.path[:0] = [str(root / "packages"), str(root)]
        from interpreter import build_cards
        from mtg import sim, bridge_to_engine
        source, parse_report = build_cards.build()
        facts = temporary / "cards.dl"
        facts.write_text(source)
        sim._DL = facts  # Redirect this audit process only; don't change checkout artifacts.
        db = sim.load_db()
        corpus = {c["name"]: c for c in cards}
        results = []
        for index, card in enumerate(cards):
            _, dropped = bridge_to_engine.card_facts(card["name"], "alice", f"c{index}", db, corpus)
            results.append({"name": card["name"], "dropped": dropped})
    output = {"parse_report": parse_report, "records": len(results),
              "records_with_drops": sum(bool(r["dropped"]) for r in results),
              "drop_categories": dict(collections.Counter(k for r in results for k, _ in r["dropped"])),
              "cards": results}
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({k: v for k, v in output.items() if k != "cards"}, indent=2))


if __name__ == "__main__":
    main()
