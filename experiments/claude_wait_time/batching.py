"""Model calls and Claude time per game, with batched replies (play/batch.py), from Playmat recordings.

    python3 experiments/claude_wait_time/batching.py <game folder> [...]

Per game: Claude decisions, decisions answered from a plan ("auto": "batch"), other auto-answers (pass_until,
own_stack, rules), decisions the model was asked and its model calls (turns, self-checks included), plans made and
how they ended (finished, or dropped early and why), Claude's seconds, and the game's wall clock. Compare with
results.md (before batching: ~418 s median of Claude time per game).
"""
import collections, json, sys
from pathlib import Path


def game(folder):
    folder = Path(folder)
    cfg = json.loads((folder / "config.json").read_text())
    claude = [s for s, v in cfg["seats"].items() if v["kind"] == "claude"]
    rows = []
    for s in claude:
        rows += [json.loads(l) for l in (folder / f"seat-{s}.jsonl").open()]
    asked = [r for r in rows if r.get("turns")]
    planned = [r for r in rows if r.get("auto") == "batch"]
    other_auto = [r for r in rows if not r.get("turns") and r.get("auto") != "batch"]
    made = [r for r in rows if r.get("batch", {}).get("pos") == 0]
    drops = collections.Counter(r["batch_fallback"]["why"].split(":")[0] for r in rows if r.get("batch_fallback"))
    kinds = collections.Counter(r["kind"] for r in made)
    ts = [r["ts"] for r in rows if "ts" in r]
    games = [json.loads(l) for l in (folder / "games.jsonl").open()] if (folder / "games.jsonl").exists() else []
    return {
        "game": folder.name[:8], "model": rows[0].get("model") if rows else None, "effort": rows[0].get("effort") if rows else None,
        "turns": games[0].get("turns") if games else None, "winner": games[0].get("winner_text") if games else None,
        "decisions": len(rows), "asked": len(asked), "model_calls": sum(len(r["turns"]) for r in asked),
        "planned": len(planned), "other_auto": len(other_auto), "plans": len(made), "plans_by_kind": dict(kinds),
        "invalid_plans": sum(1 for r in rows if r.get("batch_invalid")), "dropped": dict(drops),
        "claude_seconds": round(sum(sum(t.get("seconds", 0) for t in r["turns"]) for r in asked)),
        "wall_minutes": round((max(ts) - min(ts)) / 60000, 1) if ts else None,
    }


if __name__ == "__main__":
    for f in sys.argv[1:]:
        print(json.dumps(game(f)))
