"""Take-back marks for Playmat recordings made before GameRecorder wrote them itself (and the rules both share).

  python3 engine/playmat/fix_resumed_recordings.py [--root ~/mtg-data/playmat-games] [--apply]

Dry run by default: prints what it would change. With --apply it writes the changes, keeping each file it rewrites
once as <name>.orig next to it (an existing .orig is never overwritten). Running it again changes nothing new.

Two kinds of take-back (see engine/playmat/README.md, "Take-backs"):
- a turn rollback ("Player request: Rolling back to start of turn N" in game_log.jsonl): same folder. config.json gets
  "has_rollback" and "rollbacks" [{ts, to_turn, from_turn}], the games.jsonl line "rollbacks", and in game0.jsonl every
  decision recorded before the rollback from turn N on gets "superseded": true, "superseded_by": "rollback"; those
  after the first rollback get "after_rollback": true.
- a resume ("The game carries on from the start of turn N" at the top of game_log.jsonl): a new folder. The earlier
  recording is the latest folder of the same day or the day before with the same players (kind and name per seat,
  whatever their letters) that started earlier, reached turn N, isn't carried on elsewhere already, and whose
  games.jsonl was written at most ten minutes before the new game started (or that has none). The new folder's
  config.json gets "resumed_from" (game id), "resumed_from_turn", "resumed_from_dir", "resumed_from_seats" (seat
  letter here -> there); the earlier one gets superseded_by.json {game_id, from_turn, ts, dir}, "superseded_by" in
  config.json, "ended_by": "resumed elsewhere" (and "superseded_by", "superseded_from_turn") on its games.jsonl line,
  and its decisions from turn N on are marked "superseded": true, "superseded_by": "resume:<new game id>".
  A resumed folder's deck files were written from library and hand only (fewer than 40 cards): when the earlier
  recording's deck file for the same player has 40 cards and contains every card of the short one, it replaces it
  (the short one is kept as deck-X.partial.dck, config.json says "deck_fixed_from").

superseded() and seat_history() are also used by claude_service.py.
"""
import argparse, json, shutil, sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROLLBACK = "Rolling back to start of turn "
RESUMED = "The game carries on from the start of turn "
RESUME_WINDOW_MS = 10 * 60 * 1000


def turn_of(rec):
    try:
        return rec["obs"]["entries"][0]["turn"]
    except (KeyError, IndexError, TypeError):
        return None


def superseded(rec, rollbacks, by=None):
    """Why a decision didn't stand, or None: "rollback" (recorded before a rollback to a turn at or before its own) or
    "resume:<game id>" (from the turn a later game carried on from; by = superseded_by.json). Same rule as
    GameRecorder.supersededHow."""
    t = turn_of(rec)
    if t is None:
        return None
    ts = rec.get("ts", 0)
    for rb in rollbacks or ():
        if ts < rb["ts"] and t >= rb["to_turn"]:
            return "rollback"
    if by and t >= by["from_turn"]:
        return f"resume:{by['game_id']}"
    return None


def read_jsonl(path):
    out = []
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def seat_history(folder, seat, upto_turn=None, depth=0):
    """A seat's own recorded decisions in a folder, oldest first, each a copy with "undone": None, "a rollback" or
    "a take-back" (a later game carried this one on from upto_turn). Earlier recordings this one resumed come first
    (config.json's resumed_from_dir and resumed_from_seats). Read from the seat file, so it works while that game is
    still being recorded."""
    folder = Path(folder)
    cfg = json.loads((folder / "config.json").read_text()) if (folder / "config.json").exists() else {}
    out = []
    prev, prev_seat = cfg.get("resumed_from_dir"), (cfg.get("resumed_from_seats") or {}).get(seat)
    if prev and prev_seat and depth < 10 and Path(prev).is_dir():
        out = seat_history(prev, prev_seat, cfg.get("resumed_from_turn"), depth + 1)
    by = {"game_id": "later", "from_turn": upto_turn} if upto_turn is not None else None
    for r in read_jsonl(folder / f"seat-{seat}.jsonl"):
        how = superseded(r, cfg.get("rollbacks"), by)
        out.append({**r, "undone": None if how is None else ("a rollback" if how == "rollback" else "a take-back")})
    return out


# ---------- the fix ----------

def players(cfg):
    return sorted(f"{s.get('kind')}|{s.get('name')}" for s in cfg.get("seats", {}).values())


def seat_map(cfg, other):
    return {k: ok for k, s in cfg.get("seats", {}).items() for ok, o in other.get("seats", {}).items()
            if (s.get("kind"), s.get("name")) == (o.get("kind"), o.get("name"))}


def deck_counts(path):
    c = Counter()
    if path.exists():
        for line in path.read_text().splitlines():
            n, _, rest = line.strip().partition(" ")
            if n.isdigit():
                c[rest] += int(n)
    return c


class Folder:
    def __init__(self, path):
        self.path = path
        self.cfg = json.loads((path / "config.json").read_text())
        self.log = read_jsonl(path / "game_log.jsonl")
        self.games = read_jsonl(path / "games.jsonl")
        gj = path / "games.jsonl"
        self.games_mtime = gj.stat().st_mtime * 1000 if gj.exists() else None
        self.started = self.cfg.get("started_ms", 0)
        self.day = path.parent.name
        sb = path / "superseded_by.json"
        self.superseded_by = json.loads(sb.read_text()) if sb.exists() else self.cfg.get("superseded_by")
        self.rollbacks = [{"ts": o["ts"], "to_turn": int(o["text"].split(ROLLBACK)[1].split()[0]), "from_turn": o["turn"]}
                          for o in self.log if o.get("type") == "INFO" and ROLLBACK in o.get("text", "")]
        self.resumed_turn = next((int(o["text"].split(RESUMED)[1].split()[0]) for o in self.log[:5]
                                  if o.get("type") == "INFO" and RESUMED in o.get("text", "")), None)

    def last_turn(self):
        if self.games:
            return self.games[0].get("turns", 0)
        return max((o.get("turn", 0) for o in self.log), default=0)


def find_previous(f, folders, claimed):
    days = {f.day, (date.fromisoformat(f.day) - timedelta(days=1)).isoformat()}
    best = None
    for o in folders:
        if o is f or o.day not in days or o.started >= f.started or players(o.cfg) != players(f.cfg):
            continue
        if o.last_turn() < f.resumed_turn:
            continue
        taken = claimed.get(o.path) or (o.superseded_by or {}).get("game_id")
        if taken and taken != f.cfg["game_id"]:
            continue
        if o.games_mtime is not None and o.games_mtime < f.started - RESUME_WINDOW_MS:
            continue
        if best is None or o.started > best.started:
            best = o
    return best


def full_deck(f, seat, depth=0):
    """The 40-card deck file of a seat: its own, or (a resumed folder with a short one) the earlier recording's."""
    own = f.path / f"deck-{seat}.dck"
    prev = getattr(f, "prev", None)
    if sum(deck_counts(own).values()) == 40 or prev is None or depth > 10:
        return own
    pseat = seat_map(f.cfg, prev.cfg).get(seat)
    return full_deck(prev, pseat, depth + 1) if pseat else own


class Plan:
    def __init__(self, apply):
        self.apply, self.changes = apply, 0

    def backup(self, path):
        orig = path.with_name(path.name + ".orig")
        if path.exists() and not orig.exists():
            shutil.copy2(path, orig)

    def write(self, path, text, what):
        old = path.read_text() if path.exists() else None
        if old == text:
            return
        self.changes += 1
        print(f"  {'write' if self.apply else 'would write'} {path.parent.name[:8]}/{path.name}: {what}")
        if self.apply:
            self.backup(path)
            path.write_text(text)


def remark_game0(f, by, plan):
    """game0.jsonl with the take-back marks, from its own lines (earlier marks are recomputed)."""
    path = f.path / "game0.jsonl"
    if not path.exists():
        if f.rollbacks or by:
            print(f"  {f.path.name[:8]}: no game0.jsonl (game not finished): nothing to mark")
        return
    recs = read_jsonl(path)
    first = min((rb["ts"] for rb in f.rollbacks), default=None)
    n = Counter()
    for r in recs:
        for k in ("superseded", "superseded_by", "after_rollback"):
            r.pop(k, None)
        how = superseded(r, f.rollbacks, by)
        if how:
            r["superseded"], r["superseded_by"] = True, how
            n[how] += 1
        if first is not None and r.get("ts", 0) > first:
            r["after_rollback"] = True
            n["after_rollback"] += 1
    plan.write(path, "".join(json.dumps(r) + "\n" for r in recs),
               f"{len(recs)} decisions, " + (", ".join(f"{v} {k}" for k, v in sorted(n.items())) or "none marked"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path.home() / "mtg-data/playmat-games"))
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    args = ap.parse_args()
    root = Path(args.root).expanduser()
    folders = [Folder(p.parent) for p in sorted(root.glob("*/*/config.json"))]
    plan = Plan(args.apply)
    print(f"{len(folders)} game folders under {root}{'' if args.apply else ' (dry run: nothing is written)'}")

    # resumes, oldest first, so a chain (A resumed in B, B in C) links each to the one before
    claimed, links = {}, {}
    for f in sorted((f for f in folders if f.resumed_turn is not None), key=lambda f: f.started):
        prev = find_previous(f, folders, claimed)
        print(f"{f.day}/{f.path.name[:8]} carries on from turn {f.resumed_turn} of "
              + (f"{prev.day}/{prev.path.name[:8]}" if prev else "no recording found"))
        if prev:
            claimed[prev.path] = f.cfg["game_id"]
            ts = next(o["ts"] for o in f.log if RESUMED in o.get("text", ""))
            links[prev.path] = {"game_id": f.cfg["game_id"], "from_turn": f.resumed_turn, "ts": ts, "dir": str(f.path)}
        f.prev = prev

    for f in folders:
        cfg = dict(f.cfg)
        by = links.get(f.path) or f.superseded_by
        if not (f.rollbacks or by or f.resumed_turn is not None):
            continue
        print(f"{f.day}/{f.path.name[:8]}:")
        if f.rollbacks:
            cfg["has_rollback"], cfg["rollbacks"] = True, f.rollbacks
        if f.resumed_turn is not None:
            prev = f.prev
            cfg["resumed_from_turn"] = f.resumed_turn
            cfg["resumed_from"] = prev.cfg["game_id"] if prev else None
            if prev:
                cfg["resumed_from_dir"] = str(prev.path)
                cfg["resumed_from_seats"] = seat_map(f.cfg, prev.cfg)
                fixed = dict(cfg.get("deck_fixed_from") or {})
                for seat, pseat in cfg["resumed_from_seats"].items():
                    mine, theirs = f.path / f"deck-{seat}.dck", full_deck(prev, pseat)
                    have, full = deck_counts(mine), deck_counts(theirs)
                    if sum(have.values()) == 40 or sum(full.values()) != 40:
                        continue
                    if have - full:
                        cfg.setdefault("warnings", []).append(f"deck-{seat}.dck has cards {theirs} doesn't: {dict(have - full)}")
                        continue
                    partial = mine.with_name(f"deck-{seat}.partial.dck")
                    print(f"  {'replace' if args.apply else 'would replace'} deck-{seat}.dck ({sum(have.values())} cards) "
                          f"with {theirs.parent.name[:8]}/{theirs.name} (40), the short one kept as {partial.name}")
                    plan.changes += 1
                    if args.apply:
                        if not partial.exists():
                            shutil.copy2(mine, partial)
                        shutil.copy2(theirs, mine)
                    fixed[seat] = str(theirs)
                if fixed:
                    cfg["deck_fixed_from"] = fixed
        if by:
            cfg["superseded_by"] = by
            plan.write(f.path / "superseded_by.json", json.dumps(by, indent=2), f"carried on in {by['game_id'][:8]} from turn {by['from_turn']}")
        plan.write(f.path / "config.json", json.dumps(cfg, indent=2), "take-back fields")
        if f.games:
            games = []
            for g in f.games:
                g = dict(g)
                if f.rollbacks:
                    g["rollbacks"] = f.rollbacks
                if f.resumed_turn is not None:
                    g["resumed_from"], g["resumed_from_turn"] = cfg.get("resumed_from"), f.resumed_turn
                if by:
                    g.update(ended_by="resumed elsewhere", superseded_by=by["game_id"], superseded_from_turn=by["from_turn"])
                games.append(g)
            plan.write(f.path / "games.jsonl", "".join(json.dumps(g) + "\n" for g in games),
                       "ended_by: resumed elsewhere" if by else "take-back fields")
        if f.rollbacks or by:
            remark_game0(f, by, plan)
    print(f"{plan.changes} change(s) {'written' if args.apply else 'to write (run with --apply)'}")


if __name__ == "__main__":
    sys.exit(main())
