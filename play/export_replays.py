"""Export recorded games (Claude vs Claude, Playmat) for other projects, in two shapes. The decision logs stay the
source of truth; both exports are derived from them and lose detail.

  python3 play/export_replays.py --manifest <manifest.jsonl> [--manifest ...] --out <dir> [--verdict clean] [--human NAME ...]

Inputs are play/manifest.py manifests: one row per finished game with its file and verdict. Only rows with the given
verdict are exported (default clean). Each game is read from its gameN.jsonl (both seats' decisions, in order),
config.json and games.jsonl next to it; decisions marked "superseded" (undone by a take-back) are skipped.

Outputs in --out:
- draftzero-style.jsonl.gz: one line per seat per game, in the layout of DraftZero's self-play dataset
  (huggingface.co/datasets/danbrooks/draftzero-selfplay-games: pair, swap, seat, bot, result, records). We have no
  search, MageZero feature hashes or FDN action vocabulary, so `features`, `q` and `heuristic` are null, `legal` is the
  options as readable text, and `visits` is one-hot on the option played. Each record also carries our observation
  (what this seat could see) and, for Claude, its stated reason.
- 17lands-style.csv.gz: one row per seat per game, with 17lands replay_data column names and Arena card ids
  (cards.csv). Rebuilt from the decision logs, which see the game only when a seat had a choice; the end-of-turn
  columns are the state at the next decision after the turn ended. Columns we can't rebuild are left out (mana spent,
  combat damage, kills, discards, tutors, ability ids); see docs/research/draftzero-export-mapping-2026-10-27.md.
- export-manifest.jsonl: per game, what was exported and the cards whose ids could not be found, or why it was
  left out (a human player not passed with --human, a deck with cards outside DSK, a missing deck file).
"""
import argparse, csv, gzip, json, re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_CSV = Path.home() / "mtg-data/17lands/cards.csv"
THEIR_TYPE = {"PRIORITY": "PRIORITY", "USE": "CHOOSE_USE", "TARGET": "CHOOSE_TARGET", "BLOCK": "CHOOSE_TARGET"}
STEP_ORDER = ["null", "Untap", "Upkeep", "Draw", "Precombat Main", "Begin Combat", "Declare Attackers",
              "Declare Blockers", "First Strike Damage", "Combat Damage", "End Combat", "Postcombat Main", "End Turn",
              "Cleanup"]


def card_ids(path):
    """Card name -> Arena id, DSK first, then its tokens (TDSK, keyed by "<name> Token" as XMage names them)."""
    ids = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            if row["expansion"] == "DSK":
                ids.setdefault(row["name"], int(row["id"]))
                if " // " in row["name"]:
                    ids.setdefault(row["name"].split(" // ")[0], int(row["id"]))
            elif row["expansion"] == "TDSK":
                ids.setdefault(row["name"] + " Token", int(row["id"]))
                ids.setdefault(row["name"], int(row["id"]))
    return ids


def read_deck(path):
    out = Counter()
    for line in Path(path).read_text().splitlines():
        m = re.match(r"(\d+) \[[^\]]*\] (.+)", line.strip())
        if m and not line.startswith("SB:"):
            out[m.group(2)] += int(m.group(1))
    return out


def find_deck(game_dir, cfg, seat):
    p = cfg.get(f"deck_{seat.lower()}") or ""
    for cand in (Path(p), ROOT / p, game_dir / Path(p).name, game_dir / f"deck-{seat}.dck"):
        if p and cand.is_file():
            return cand
    return None


def load_game(row, remap):
    gf = Path(row["file"])
    for old, new in remap:
        if str(gf).startswith(old):
            gf = Path(new + str(gf)[len(old):])
    d = gf.parent
    cfg = json.loads((d / "config.json").read_text()) if (d / "config.json").exists() else {}
    g = int(re.search(r"game(\d+)\.jsonl$", gf.name).group(1))
    end = {}
    if (d / "games.jsonl").exists():
        for line in (d / "games.jsonl").read_text().splitlines():
            e = json.loads(line) if line.strip() else {}
            if e.get("game") == g and "winner" in e:
                end = e
    recs = []
    for line in gf.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "kind" in r and not r.get("superseded"):
            recs.append(r)
    return d, g, cfg, end, recs


def glob_(r):
    return r["obs"]["entries"][0]


def entry(r, ref):
    """The observation entry an option's source or target points at."""
    i = (ref or {}).get("entry")
    es = r["obs"]["entries"]
    if i is None:
        return None
    if i < len(es) and es[i].get("i") == i:
        return es[i]
    return next((e for e in es if e.get("i") == i), None)


def name_of(e):
    if not e or e.get("face_down"):
        return None
    return e.get("card_name") or e.get("name")


def bot_of(cfg, row, seat):
    s = cfg.get("seats", {}).get(seat, {})
    return row.get(seat.lower()) or s.get("player") or (f"human:{s.get('name')}" if s.get("kind") == "human" else s.get("kind"))


def result_of(end, seat):
    if not end or end.get("draw") or end.get("winner") not in ("A", "B"):
        return None
    return 1 if end["winner"] == seat else -1


# ---------- DraftZero-style ----------

def draftzero_lines(row, d, g, cfg, end, recs):
    for seat in "AB":
        mine = [r for r in recs if r["seat"] == seat]
        out = []
        for r in mine:
            gl = glob_(r)
            n = len(r["options"])
            ch = r.get("choice")
            out.append({
                "type": THEIR_TYPE.get(r["kind"], r["kind"]), "kind": r["kind"], "turn": gl.get("turn"),
                "step": gl.get("step"), "prompt": r.get("prompt"),
                "legal": [o.get("label") for o in r["options"]],
                "legal_actions": [{"action": o.get("action"), "source": name_of(entry(r, o.get("source"))),
                                   "target": name_of(entry(r, o.get("target"))) or (o.get("target") or {}).get("player")}
                                  for o in r["options"]],
                "visits": [int(i == ch) for i in range(n)] if isinstance(ch, int) else None,
                "chosen": ch, "q": None, "heuristic": None, "features": None,
                "decided_by": r.get("source"), "auto": bool(r.get("auto")),
                "reason": r.get("reason"), "obs": r["obs"],
            })
        deck = find_deck(d, cfg, seat)
        yield {
            "pair": cfg.get("game_id") or f"{row.get('run')}/{row.get('part')}/game{g}", "swap": None, "seat": seat,
            "bot": bot_of(cfg, row, seat), "opp_bot": bot_of(cfg, row, "B" if seat == "A" else "A"),
            "result": result_of(end, seat), "set": "DSK", "source": cfg.get("source") or "claude-games",
            "first": end.get("first"), "turns": end.get("turns"), "code_commit": row.get("code_commit"),
            "xmage": cfg.get("xmage"), "verdict": row.get("verdict"),
            "deck": dict(read_deck(deck)) if deck else None, "records": out,
        }


# ---------- 17lands-style ----------

def board(r, mine):
    """(lands, creatures, other permanents) on one side of the battlefield, face-down cards left out."""
    lands, crs, other = [], [], []
    for e in r["obs"]["entries"][1:]:
        if e.get("kind") != "card" or e.get("zone") != "BATTLEFIELD" or e.get("mine") != mine:
            continue
        n = name_of(e)
        if not n:
            continue
        t = e.get("types") or ""
        (lands if "Land" in t else crs if "Creature" in t else other).append(n)
    return lands, crs, other


def hand(r):
    return Counter(name_of(e) for e in r["obs"]["entries"][1:]
                   if e.get("kind") == "card" and e.get("zone") == "HAND" and e.get("mine") and name_of(e))


def side_life(r, user):
    gl = glob_(r)
    me = r["seat"] == user
    return ((gl.get("my_life") if me else gl.get("opp_life")), (gl.get("opp_life") if me else gl.get("my_life")),
            (gl.get("opp_hand") if me else gl.get("my_hand")))


def seventeenlands_rows(row, d, g, cfg, end, recs, ids, missing):
    first = end.get("first") or "A"
    turns = max([glob_(r).get("turn") or 0 for r in recs] + [end.get("turns") or 0])
    active = {t: (first if t % 2 == 1 else ("B" if first == "A" else "A")) for t in range(1, turns + 1)}
    by_turn = defaultdict(list)
    for r in recs:
        by_turn[glob_(r).get("turn") or 0].append(r)

    def idlist(names):
        out = []
        for n in names:
            if n in ids:
                out.append(str(ids[n]))
            else:
                missing[n] += 1
        return "|".join(out)

    # What each seat did each turn, from its own chosen options.
    acts = defaultdict(lambda: defaultdict(list))  # (turn, seat) -> column -> names
    mulls, cand = Counter(), defaultdict(list)
    for r in recs:
        ch, s, t = r.get("choice"), r["seat"], glob_(r).get("turn") or 0
        if not isinstance(ch, int) or ch >= len(r["options"]):
            continue
        o = r["options"][ch]
        a, src = o.get("action"), entry(r, o.get("source"))
        n = name_of(src)
        if r["kind"] == "USE" and (r.get("prompt") or "").startswith("Mulligan?"):
            cand[s].append(hand(r))
            mulls[s] += a == "YES"
        elif a == "PLAY_LAND" and n:
            acts[t, s]["lands_played"].append(n)
        elif a == "CAST" and n:
            ty = src.get("types") or ""
            if "Instant" in ty or "Sorcery" in ty:
                acts[t, s]["instants_sorceries_cast"].append(n)
            elif "Creature" in ty:
                acts[t, s]["creatures_cast"].append(n)
            else:
                acts[t, s]["non_creatures_cast"].append(n)
        elif a in ("ACTIVATE", "SPECIAL") and n:
            acts[t, s]["ability_sources"].append(n)
        elif a == "ATTACK" and n:
            acts[t, s]["creatures_attacked"].append(n)
        elif a == "BLOCK" and n:
            acts[t, s]["creatures_blocking"].append(n)
            att = name_of(entry(r, o.get("target")))
            if att:
                acts[t, s]["attackers_blocked"].append(att)

    # The state at the end of turn t: the first decision of a later turn (it sees everything done in turn t), else
    # the game's last decision with the final life totals.
    def eot(t):
        for u in range(t + 1, turns + 2):
            if by_turn.get(u):
                return by_turn[u][0], u
        return (recs[-1] if recs else None), None

    rows = []
    for user in "AB":
        opp = "B" if user == "A" else "A"
        mine = [r for r in recs if r["seat"] == user]
        out = {"expansion": "DSK", "event_type": "PlaymatHuman" if cfg.get("source") == "playmat" else "ClaudeSelfPlay",
               "draft_id": cfg.get("game_id") or f"{row.get('run')}/{row.get('part')}", "game_number": g,
               "on_play": first == user, "num_mulligans": mulls[user], "opp_num_mulligans": mulls[opp],
               "won": result_of(end, user) == 1 if result_of(end, user) is not None else "",
               "x_seat": user, "x_bot": bot_of(cfg, row, user), "x_opp_bot": bot_of(cfg, row, opp)}
        for i, h in enumerate(cand[user][:7], 1):
            out[f"candidate_hand_{i}"] = idlist(sorted(h.elements()))
        # Opening hand: the hand at the seat's first decision after the mulligans and bottoming.
        pregame = lambda r: glob_(r).get("step") == "null"
        k0 = next((i for i, r in enumerate(mine) if not pregame(r)), len(mine))
        opening = hand(mine[k0]) if k0 < len(mine) else None
        if opening is not None:
            out["opening_hand"] = idlist(sorted(opening.elements()))
        # Cards that came into the hand since the seat's previous decision (draws, mostly), on the turn they were seen.
        seen, drawn = [], defaultdict(list)
        prev = opening or Counter()
        for r in mine[k0:]:
            h = hand(r)
            added = h - prev
            seen.append((r, h, added))
            drawn[glob_(r).get("turn") or 0] += list(added.elements())
            prev = h
        n_turn = {user: 0, opp: 0}
        totals = Counter()
        for t in range(1, turns + 1):
            who = active[t]
            n_turn[who] += 1
            pre = f"{'user' if who == user else 'oppo'}_turn_{n_turn[who]}_"
            A = acts[t, who]
            for col in ("lands_played", "creatures_cast", "non_creatures_cast"):
                if A[col]:
                    out[pre + col] = idlist(A[col])
                    totals[("user_" if who == user else "oppo_") + col] += len(A[col])
            for s, side in ((user, "user"), (opp, "oppo")):
                if acts[t, s]["instants_sorceries_cast"]:
                    out[pre + f"{side}_instants_sorceries_cast"] = idlist(acts[t, s]["instants_sorceries_cast"])
                    totals[f"{side}_instants_sorceries_cast"] += len(acts[t, s]["instants_sorceries_cast"])
                if acts[t, s]["ability_sources"]:
                    out[pre + f"x_{side}_ability_sources"] = idlist(acts[t, s]["ability_sources"])
            defender = opp if who == user else user
            att, blk = A["creatures_attacked"], acts[t, defender]["attackers_blocked"]
            if att:
                out[pre + "creatures_attacked"] = idlist(att)
                unb = list((Counter(att) - Counter(blk)).elements())
                if unb:
                    out[pre + "creatures_unblocked"] = idlist(unb)
            if blk:
                out[pre + "creatures_blocked"] = idlist(blk)
            if acts[t, defender]["creatures_blocking"]:
                out[pre + "creatures_blocking"] = idlist(acts[t, defender]["creatures_blocking"])
            if who == user and drawn.get(t):
                out[pre + "cards_drawn"] = idlist(drawn[t])
                totals["user_cards_drawn"] += len(drawn[t])
            r, nxt = eot(t)
            if r is None:
                continue
            me = r["seat"] == user
            ul, uc, uo = board(r, me)
            ol, oc, oo = board(r, not me)
            for col, names in (("eot_user_lands_in_play", ul), ("eot_user_creatures_in_play", uc),
                               ("eot_user_non_creatures_in_play", uo), ("eot_oppo_lands_in_play", ol),
                               ("eot_oppo_creatures_in_play", oc), ("eot_oppo_non_creatures_in_play", oo)):
                if names:
                    out[pre + col] = idlist(names)
            # The user's hand: its first view in a later turn, without what came into it since its previous view;
            # else (the game's last turn) its last view.
            later = next(((h, added) for x, h, added in seen if (glob_(x).get("turn") or 0) > t), None)
            if later or seen:
                h = later[0] - later[1] if later else seen[-1][1]
                out[pre + "eot_user_cards_in_hand"] = idlist(sorted(h.elements()))
            ulife, olife, ohand = side_life(r, user)
            if nxt is None and end:
                ulife, olife = end.get(f"life_{user.lower()}", ulife), end.get(f"life_{opp.lower()}", olife)
            out[pre + "eot_user_life"], out[pre + "eot_oppo_life"] = ulife, olife
            out[pre + "eot_oppo_cards_in_hand"] = ohand
        out["num_turns"] = max(n_turn.values())
        for k, v in totals.items():
            out[k.replace("user_", "user_total_", 1).replace("oppo_", "oppo_total_", 1)] = v
        deck = find_deck(d, cfg, user)
        if deck:
            for n, c in read_deck(deck).items():
                out[f"deck_{n}"] = c
                if n not in ids:
                    missing[n] += 1
        rows.append(out)
    return rows


def column_order(keys):
    def key(k):
        m = re.match(r"(user|oppo)_turn_(\d+)_(.+)", k)
        if m:
            return (1, int(m.group(2)), m.group(1) == "oppo", m.group(3))
        if k.startswith("deck_"):
            return (3, 0, False, k)
        if k.startswith("x_"):
            return (4, 0, False, k)
        if "_total_" in k:
            return (2, 0, False, k)
        return (0, 0, False, "")
    fixed = ["expansion", "event_type", "draft_id", "game_number", "on_play", "num_mulligans", "opp_num_mulligans",
             "num_turns", "won"] + [f"candidate_hand_{i}" for i in range(1, 8)] + ["opening_hand"]
    rest = sorted((k for k in keys if k not in fixed), key=key)
    return [k for k in fixed if k in keys] + rest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--verdict", default="clean")
    ap.add_argument("--human", action="append", default=[],
                    help="a human player whose games may be exported (repeatable); games with any other human are left out")
    ap.add_argument("--remap", action="append", default=[], help="OLD=NEW prefix for game file paths")
    ap.add_argument("--cards", default=str(CARDS_CSV))
    a = ap.parse_args()
    remap = [tuple(x.split("=", 1)) for x in a.remap]
    ids = card_ids(a.cards)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows17, n_games, n_dec = [], 0, 0
    with gzip.open(out / "draftzero-style.jsonl.gz", "wt") as dz, open(out / "export-manifest.jsonl", "w") as em:
        for mf in a.manifest:
            for line in open(mf):
                row = json.loads(line)
                if row.get("verdict") != a.verdict:
                    continue
                d, g, cfg, end, recs = load_game(row, remap)
                humans = {s.get("name") for s in cfg.get("seats", {}).values() if s.get("kind") == "human"}
                decks = [find_deck(d, cfg, s) for s in "AB"]
                off_set = sorted({n for p in decks if p for n in read_deck(p) if n not in ids})
                skip = ("human players not allowed: " + ", ".join(sorted(humans - set(a.human))) if humans - set(a.human)
                        else "not a DSK deck: " + ", ".join(off_set) if off_set
                        else "deck file not found" if not all(decks) else None)
                if skip:
                    em.write(json.dumps({"game": str(d / f"game{g}.jsonl"), "skipped": skip}) + "\n")
                    continue
                missing = Counter()
                for seat_line in draftzero_lines(row, d, g, cfg, end, recs):
                    dz.write(json.dumps(seat_line) + "\n")
                rows17 += seventeenlands_rows(row, d, g, cfg, end, recs, ids, missing)
                n_games += 1
                n_dec += len(recs)
                em.write(json.dumps({"game": str(d / f"game{g}.jsonl"), "verdict": row.get("verdict"),
                                     "decisions": len(recs), "first": end.get("first"), "winner": end.get("winner"),
                                     "unmapped_cards": dict(missing)}) + "\n")
    cols = column_order({k for r in rows17 for k in r})
    with gzip.open(out / "17lands-style.csv.gz", "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows17)
    print(f"{n_games} games, {n_dec} decisions, {len(rows17)} 17lands-style rows -> {out}")


if __name__ == "__main__":
    main()
