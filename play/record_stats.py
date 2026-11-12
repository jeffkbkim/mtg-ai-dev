"""Jeff's record against Claude in Playmat games, by the counting rules agreed in the project thread.

  python3 play/record_stats.py [--root ~/mtg-data/playmat-games]

Counted: finished games between one of Jeff's names and a Claude Opus seat, at their final recording. Left out:
recordings a later table carried on (superseded_by / "resumed elsewhere"), games of 2 turns or fewer, games ended by a
server restart or a resume error, and (Jeff 2026-11-12) games where any Claude decision was the service's fallback
because the model call failed ("service_error": logged out, usage limit). Quick Draft games are counted separately.
"""
import argparse, json
from collections import Counter
from pathlib import Path

JEFF = {"binpy", "binpy2", "kimster", "ffffxxxx"}
ENDED_OUT = {"resumed elsewhere", "server_restart", "resume_error"}


def lines(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def service_failed(folder):
    return any('"service_error": true' in f.read_text() for f in folder.glob("seat-*.jsonl"))


def tally(root):
    counts = {"regular": Counter(), "quick draft": Counter()}
    left_out = Counter()
    for gf in sorted(root.glob("*/*/games.jsonl")):
        folder = gf.parent
        cfg = json.loads((folder / "config.json").read_text()) if (folder / "config.json").exists() else {}
        for g in lines(gf):
            seats = {"A": g.get("a", ""), "B": g.get("b", "")}
            human = next((s for s, p in seats.items() if p.startswith("human:") and p.split(":", 1)[1] in JEFF), None)
            other = seats.get("B" if human == "A" else "A", "")
            if not human or not other.startswith("claude:claude-opus"):
                continue
            if g.get("superseded_by") or cfg.get("superseded_by") or g.get("ended_by") in ENDED_OUT:
                left_out["carried on or ended by the server"] += 1
                continue
            if (g.get("turns") or 0) <= 2:
                left_out["2 turns or fewer"] += 1
                continue
            if service_failed(folder):
                left_out["Claude's model calls failed (service_error): " + folder.name[:8]] += 1
                continue
            deck = (cfg.get("seats", {}).get(human, {}).get("deck_name") or "").lower()
            kind = "quick draft" if "quick draft" in deck else "regular"
            won = g.get("winner") == human
            counts[kind]["won" if won else "draw" if g.get("draw") else "lost"] += 1
    return counts, left_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path.home() / "mtg-data" / "playmat-games")
    counts, left_out = tally(ap.parse_args().root)
    for kind, c in counts.items():
        n = c["won"] + c["lost"] + c["draw"]
        print(f"{kind}: {c['won']}-{c['lost']}" + (f"-{c['draw']}" if c["draw"] else "") + (f" ({c['won'] / n:.0%})" if n else ""))
    for why, n in sorted(left_out.items()):
        print(f"  left out: {n} {why}")


if __name__ == "__main__":
    main()
