"""Replay 17lands DSK games in XMage, one turn at a time, and measure how many turns reproduce.

    uv run --group data python seventeenlands/turn_replay.py --games 20 [--seed 0] [--budget 40] [-v] [--trace g123:5]

A replay row records, per turn, which cards each player played, which creatures attacked and blocked, and the
end-of-turn state (life, the user's hand, both boards). It does not record the order of plays, whether a spell came
before or after combat, targets, or which blocker took which attacker. This script plays the game in XMage with both
seats scripted from the record (engine/xmage/ReplayMatch + ReplaySeat) and fills those gaps by search:

  1. Decks: the user's (seat A) deck is recorded. The opponent's (seat B) is the cards it revealed, plus basic lands
     as filler for the cards it never showed.
  2. Draws: each seat draws from a scripted queue. A draws its recorded candidate hands and per-turn draws. B's
     queue is the revealed cards in the order it first used them, so each is in hand by the time it is played.
  3. Each turn, both seats play what the record says for that turn: lands, spells, abilities, attacks, blocks.
     Every detail the record leaves open is a choice point with its likeliest alternative first: cast a recorded
     play now or wait, which blocker took which attacker, targets, modes, "may" answers, trigger order.
  4. In the end step the true XMage state is compared with the recorded end of turn: both life totals, A's hand,
     B's hand size and both battlefields (card names), and every recorded play must have happened. If it doesn't
     match, the turn is rewound (XMage's turn rollback) and another set of choices is tried, fewest departures
     from the likeliest choices first, up to --budget attempts per turn.
  5. A turn that no attempt reproduces is a failure. The visible state is then reset to the recorded end of turn
     (cards moved between zones without triggering anything, life set) and the game goes on. Turns after a reset
     are counted separately ("after a resync"): tapped state, counters, attachments, tokens and face-down cards
     aren't reset, so those turns start from a less exact state.

Writes ~/mtg-data/17lands/DSK/turn_replay/<run>/ (one JSON line per turn, a summary). Measurement is the point: every
failure is kept with what differed. Activated abilities, the opponent's flash permanents, and cards milled or
manifested off the top of the library are not scripted yet; turns that need them are tagged so they can be counted.
"""
from __future__ import annotations

import argparse, collections, glob, gzip, heapq, itertools, json, os, random, signal, socket, subprocess, sys, time
from pathlib import Path

import polars as pl

DATA = Path.home() / "mtg-data/17lands/DSK"
REPO = Path(__file__).resolve().parent.parent
RUNTIME = Path.home() / "xmage/xmage/mage-server"
FACE_DOWN = "[Face-Down Card]"
# 17lands Duskmourn token ids -> XMage token classes. The two Insects and two Spirits are told apart only by id
# here; which id is which class is a guess (it changes P/T and abilities, not the name the replay compares).
TOKEN_CLASS = {92388: "ShardToken", 92389: "BeastieToken", 92390: "GlimmerToken", 92391: "InsectBlackGreenFlyingToken",
               92399: "InsectWhiteToken", 92392: "Spirit31Token", 92394: "SpiritBlueToken", 92393: "ToyToken",
               92395: "Demon66Token", 92396: "HorrorEnchantmentCreatureToken", 92397: "Gremlin11Token",
               92398: "Spider22Token", 92400: "PrimoTheIndivisibleToken", 92401: "TreasureToken", 92402: "EverywhereToken"}
BASICS = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}


# ---------------------------------------------------------------- names

class Names:
    """17lands ids -> names XMage uses: a split card / Room's halves are the whole card, tokens lose " Token"."""

    def __init__(self):
        cards = pl.read_csv(DATA.parent / "cards.csv")
        raw = dict(zip(cards["id"], cards["name"]))
        self.full = {h: n for n in raw.values() if " // " in n for h in n.split(" // ")}
        self.name = {i: self.full.get(n, n) for i, n in raw.items()}
        self.raw = dict(raw)   # keeps a Room's door name: 17lands records which door was cast
        self.name[3] = FACE_DOWN
        # tokens by rarity: basics from sets whose code starts with T (THB, TDM ...) aren't tokens
        self.token = {i for i, r in zip(cards["id"], cards["rarity"]) if r == "token" and i != 3}
        self.types = {self.full.get(n, n): t or "" for n, t in zip(cards["name"], cards["types"])}
        text = json.loads((REPO / "engine/vocab/dsk_card_text.json").read_text())
        self.rules = {c["name"]: " ".join(c["rules"] + c.get("left", {}).get("rules", []) + c.get("right", {}).get("rules", [])) for c in text}
        self.cost = {c["name"]: c.get("cost", "") for c in text}
        # Room doors: half name -> (room, side), and each door's rules for matching its unlock trigger
        self.half_of, door_rules = {}, []
        for c in text:
            for side in ("left", "right"):
                if side in c:
                    self.half_of[c[side]["name"]] = (c["name"], side)
                    door_rules.append((c["name"], side, norm_text(" ".join(c[side]["rules"]))))
        self.door_rules = door_rules
        ab = pl.read_csv(DATA.parent / "abilities.csv")
        self.ability_text = dict(zip(ab["id"], ab["text"]))
        self._ability = {}
        numbers = json.loads((REPO / "experiments/coverage_soak/dsk_numbers.json").read_text())
        self.code = {n: (v if ":" in v else f"DSK:{v}") for n, v in numbers.items()}

    def ability(self, aid: int) -> tuple[str, str] | None:
        """(card, text) for an activated ability id, None for a triggered or unknown one. 17lands lists both kinds in
        its abilities columns; only activated ones are choices to script."""
        if aid in self._ability:
            return self._ability[aid]
        import re
        # 17lands writes mana as {oT}, {o1oB}: one brace per symbol, as XMage does
        text = re.sub(r"\{((?:o[^o{}]+)+)\}", lambda m: "".join("{" + x + "}" for x in m.group(1).split("o")[1:]),
                      self.ability_text.get(aid) or "").replace("CARDNAME", "{this}")
        out = None
        cost = text.split(":", 1)[0] if ":" in text else ""
        keyword = re.match(r"(Equip|Crew)\b", text)
        mana = re.search(r":\s*Add\b", text)
        if not mana and (keyword or cost and len(cost) < 80 and not cost.startswith(("When", "Whenever", "At "))
                         and any(k in cost for k in ("{", "Sacrifice", "Discard", "Exile", "Pay", "Tap", "Remove"))):
            key = norm_text(text)[:30]
            out = (None, norm_text(text))   # keyword abilities (Equip, Crew) match any source
            if not keyword:
                cards = [card for card, rules in self.rules.items() if key and key in norm_text(rules)]
                if len(cards) == 1:   # several cards with the same ability: match the option by text alone
                    out = (cards[0], norm_text(text))
        self._ability[aid] = out
        return out

    def door_trigger(self, aid: int) -> tuple[str, str] | None:
        """(room, side) for a 17lands "When you unlock this door" ability, else None."""
        text = self.ability_text.get(aid) or ""
        if not text.startswith("When you unlock this door"):
            return None
        t = norm_text(text.replace("CARDNAME", "{this}"))[:40]
        hits = [(room, side) for room, side, r in self.door_rules if t and t in r]
        return hits[0] if len(hits) == 1 else None

    def raw_names(self, v):
        return [self.raw.get(i, str(i)) for i in self.ids(v)]

    def ids(self, v):
        return [] if v in (None, "") else [int(x) for x in str(v).split("|") if x]

    def names(self, v, tokens=True):
        return [self.name.get(i, str(i)) for i in self.ids(v) if tokens or i not in self.token]

    def norm(self, n: str) -> str:
        n = n[:-6] if n.endswith(" Token") else n
        return self.full.get(n, n)


def norm_text(t: str) -> str:
    import re
    t = re.sub(r"\([^)]*\)", "", t or "")           # reminder text
    t = re.sub(r"<[^>]+>", "", t).replace("&mdash;", "-")
    return re.sub(r"[^a-z0-9{}]+", " ", t.lower()).strip()


# ---------------------------------------------------------------- the record

class Record:
    """One replay row, read the way XMage numbers turns: global turn t is seat A's (the user) or seat B's."""

    def __init__(self, row: dict, names: Names):
        self.r, self.n = row, names
        self.a_first = bool(row["on_play"])
        self.turns = int(row["num_turns"] or 0)

    def slot(self, t: int):
        """(active seat, 17lands prefix) for XMage turn t, or None past the recorded turns."""
        k, first = (t + 1) // 2, t % 2 == 1
        a_active = first == self.a_first
        if k > self.turns or k > 30:
            return None
        return ("A", f"user_turn_{k}_") if a_active else ("B", f"oppo_turn_{k}_")

    def L(self, prefix, field, tokens=True):
        return self.n.names(self.r.get(prefix + field), tokens)

    def num(self, prefix, field, default=None):
        v = self.r.get(prefix + field)
        return default if v in (None, "") else int(float(v))

    def prev_prefix(self, prefix: str) -> str | None:
        """The 17lands prefix of the turn before this one (the other player's), or None on the first turn."""
        side, k = prefix.split("_")[0], int(prefix.split("_")[2])
        first_side = "user" if self.a_first else "oppo"
        if side == first_side:
            return None if k == 1 else f"{'oppo' if side == 'user' else 'user'}_turn_{k - 1}_"
        return f"{first_side}_turn_{k}_"

    def board(self, prefix: str | None, who: str, tokens=False) -> collections.Counter:
        if prefix is None:
            return collections.Counter()
        return collections.Counter(self.n.norm(x) for f in ("lands", "creatures", "non_creatures")
                                   for x in self.L(prefix, f"eot_{who}_{f}_in_play", tokens))

    def plays(self, prefix: str, active: str) -> dict:
        """What each seat played in this turn, by name. The non-active player's permanent spells (flash) aren't
        recorded: a card new on its battlefield, or blocking, without having been there is taken as flashed in."""
        other = "B" if active == "A" else "A"
        mine_inst = "user_instants_sorceries_cast" if active == "A" else "oppo_instants_sorceries_cast"
        their_inst = "oppo_instants_sorceries_cast" if active == "A" else "user_instants_sorceries_cast"
        perm = self.L(prefix, "creatures_cast") + self.L(prefix, "non_creatures_cast")
        inst = self.L(prefix, mine_inst)
        spells = list((collections.Counter(perm) | collections.Counter(inst)).elements())  # some instants are listed twice
        other_who = "oppo" if active == "A" else "user"
        before = self.board(self.prev_prefix(prefix), other_who)
        after = self.board(prefix, other_who) + collections.Counter(self.n.norm(x) for x in self.L(prefix, "creatures_blocking", False))
        after = collections.Counter({k: max(after[k], self.board(prefix, other_who)[k]) for k in after})
        # only cards with flash: others reach the board on the other player's turn some other way (an Enduring
        # creature coming back as an enchantment, a reanimation) and aren't cast
        flash = [c for c in (after - before).elements() if c != FACE_DOWN and c in self.n.code
                 and "Land" not in self.n.types.get(c, "") and self.n.rules.get(c, "").startswith("Flash")]
        ab_mine = "user_abilities" if active == "A" else "oppo_abilities"
        ab_theirs = "oppo_abilities" if active == "A" else "user_abilities"
        return {
            active: {"lands": self.L(prefix, "lands_played"), "spells": spells,
                     "attack": self.L(prefix, "creatures_attacked"), "abilities": self.n.ids(self.r.get(prefix + ab_mine))},
            other: {"spells": self.L(prefix, their_inst) + flash, "flash": flash, "block": self.L(prefix, "creatures_blocking"),
                    "abilities": self.n.ids(self.r.get(prefix + ab_theirs))},
            "blocked": self.L(prefix, "creatures_blocked"),
            "noncreature_cast": self.L(prefix, "non_creatures_cast"),
            "killed": self.L(prefix, "user_creatures_killed_combat") + self.L(prefix, "user_creatures_killed_non_combat")
                      + self.L(prefix, "oppo_creatures_killed_combat") + self.L(prefix, "oppo_creatures_killed_non_combat"),
        }

    def expected(self, prefix: str) -> dict:
        bf = lambda w: sorted(self.n.norm(x) for x in self.L(prefix, f"eot_{w}_lands_in_play") + self.L(prefix, f"eot_{w}_creatures_in_play")
                              + self.L(prefix, f"eot_{w}_non_creatures_in_play"))
        return {"life_A": self.num(prefix, "eot_user_life"), "life_B": self.num(prefix, "eot_oppo_life"),
                "hand_A": sorted(self.L(prefix, "eot_user_cards_in_hand")), "hand_B": self.num(prefix, "eot_oppo_cards_in_hand"),
                "bf_A": bf("user"), "bf_B": bf("oppo")}

    def doors(self, upto_prefix: str, who: str) -> dict[str, list[str]]:
        """Room doors unlocked for one player by the end of a turn: doors it cast, and doors whose unlock trigger fired."""
        out = collections.defaultdict(set)
        for t in range(1, 2 * self.turns + 2):
            s = self.slot(t)
            if not s:
                continue
            active, p = s
            mine = (active == "A") == (who == "user")
            if mine:
                for raw in self.n.raw_names(self.r.get(p + "non_creatures_cast")):
                    if raw in self.n.half_of:
                        room, side = self.n.half_of[raw]
                        out[room].add(side)
            for aid in self.n.ids(self.r.get(p + f"{who}_abilities")):
                d = self.n.door_trigger(aid)
                if d:
                    out[d[0]].add(d[1])
            if p == upto_prefix:
                break
        return {k: sorted(v) for k, v in out.items()}

    def fix(self, prefix: str) -> dict:
        """The recorded end of turn in the form ReplaySeat.fix takes (tokens and face-down cards left out)."""
        bf = lambda w: [self.n.norm(x) for f in ("lands", "creatures", "non_creatures")
                        for x in self.L(prefix, f"eot_{w}_{f}_in_play", tokens=False) if x != FACE_DOWN or w == "oppo"]
        ids = lambda w: [i for f in ("lands", "creatures", "non_creatures") for i in self.n.ids(self.r.get(prefix + f"eot_{w}_{f}_in_play"))
                         if i in self.n.token]
        tok = lambda w: [self.n.norm(self.n.name.get(i, "")) for i in ids(w)]
        classes = lambda w: {self.n.norm(self.n.name.get(i, "")): "mage.game.permanent.token." + TOKEN_CLASS[i] for i in ids(w) if i in TOKEN_CLASS}
        out = {"A": {"battlefield": bf("user"), "tokens": tok("user"), "token_classes": classes("user"),
                     "hand": self.L(prefix, "eot_user_cards_in_hand"), "doors": self.doors(prefix, "user")},
               "B": {"battlefield": bf("oppo"), "tokens": tok("oppo"), "token_classes": classes("oppo"), "face_down_hidden": True,
                     "doors": self.doors(prefix, "oppo")}}
        # the player whose turn this was keeps its permanents tapped into the next turn: as many lands as the mana it
        # spent (an estimate: mana from other sources and lands tapped for abilities aren't told apart), and attackers
        active = "A" if prefix.startswith("user") else "B"
        who = "user" if active == "A" else "oppo"
        spent = self.num(prefix, f"{who}_mana_spent", 0)
        out[active]["tap"] = {"lands": spent, "creatures": [self.n.norm(x) for x in self.L(prefix, "creatures_attacked", False)]}
        for seat, w in (("A", "user"), ("B", "oppo")):
            life = self.num(prefix, f"eot_{w}_life")
            if life is not None:
                out[seat]["life"] = life
        hb = self.num(prefix, "eot_oppo_cards_in_hand")
        if hb is not None:
            # B's hidden hand: the cards it plays next, in order, then filler; the record only gives the count
            nxt = []
            k = next((t for t in range(1, 2 * self.turns + 2) if self.slot(t) and self.slot(t)[1] == prefix), None)
            for t in range((k or 0) + 1, 2 * self.turns + 2):
                s = self.slot(t)
                if s:
                    b = self.plays(s[1], s[0])["B"]
                    nxt += [c for c in b.get("lands", []) + b.get("spells", []) if c in self.n.code]
            board = self.board(prefix, "oppo")
            hand = nxt[:hb]
            out["B"]["hand"] = hand
            out["B"]["hand_count"] = hb
        return out

    def deck_a(self) -> collections.Counter:
        return collections.Counter({c[5:]: int(self.r[c]) for c in self.r if c.startswith("deck_") and self.r[c]})

    def hands_a(self) -> list[list[str]]:
        return [self.n.names(self.r[f"candidate_hand_{i}"]) for i in range(1, 8) if self.r.get(f"candidate_hand_{i}")]

    def b_sequence(self) -> list[str]:
        """Cards B used, in the order it first needed them in hand (lands, casts, instants)."""
        seq = []
        for t in range(1, 2 * self.turns + 2):
            s = self.slot(t)
            if not s:
                continue
            active, p = s
            pl_ = self.plays(p, active)
            b = pl_["B"]
            seq += b.get("lands", []) + b.get("spells", [])
        return [c for c in seq if c in self.n.code]

    def a_draws_by_turn(self) -> dict[int, list[str]]:
        """A's draws per XMage turn: recorded draws on its turns, and cards that appear in its hand on B's turns
        without a record (instants that drew, off-turn draws), placed in that turn."""
        out = {}
        hand = collections.Counter(self.n.names(self.r.get("opening_hand")))
        for t in range(1, 2 * self.turns + 2):
            s = self.slot(t)
            if not s:
                continue
            active, p = s
            pl_ = self.plays(p, active)
            if active == "A":
                drawn = self.L(p, "cards_drawn")
                hand += collections.Counter(drawn + self.L(p, "cards_tutored"))
                hand -= collections.Counter(pl_["A"]["lands"] + pl_["A"]["spells"] + self.L(p, "cards_discarded"))
                out[t] = drawn
            else:
                hand -= collections.Counter(pl_["A"]["spells"])
                truth = collections.Counter(self.L(p, "eot_user_cards_in_hand"))
                extra = list((truth - hand).elements())
                out[t] = extra
                hand = truth
                continue
            hand = collections.Counter(self.L(p, "eot_user_cards_in_hand"))
        return out


# ---------------------------------------------------------------- decks and the game spec

def write_deck(path: Path, cards: collections.Counter, names: Names):
    lines = [f"{k} [{names.code[c]}] {c}" for c, k in sorted(cards.items()) if k > 0]
    path.write_text(f"NAME:{path.stem}\n" + "\n".join(lines) + "\n")


def game_spec(rec: Record, names: Names, out: Path, gid) -> tuple[dict, list[str]]:
    """Deck files and the opening draw queues. Returns the spec and problems that rule the game out."""
    problems = []
    deck_a = rec.deck_a()
    missing = [c for c in deck_a if c not in names.code]
    if missing:
        problems.append("deck A has cards outside our list: " + ", ".join(missing))
    seq = rec.b_sequence()
    need = collections.Counter(seq)
    for t in range(1, 2 * rec.turns + 2):   # cards that reach B's board some other way still have to exist
        s = rec.slot(t)
        if s:
            on_board = collections.Counter(c for c in rec.board(s[1], "oppo").elements() if c in names.code)
            need = need | on_board
    # B's deck: every card it showed, as many copies as it ever used, plus basics for the cards it never showed
    colors = [c for c in (rec.r.get("opp_colors") or "") if c in BASICS] or ["W"]
    deck_b = collections.Counter(need)
    for i in range(max(0, 40 - sum(deck_b.values()))):
        deck_b[BASICS[colors[i % len(colors)]]] += 1
    da, db = out / f"{gid}_A.dck", out / f"{gid}_B.dck"
    write_deck(da, deck_a, names)
    write_deck(db, deck_b, names)
    draws_a = [c for h in rec.hands_a() for c in h]
    spec = {"id": gid, "deck_a": str(da), "deck_b": str(db), "first": "A" if rec.a_first else "B",
            "draws_a": draws_a, "draws_b": seq, "reset_on_shuffle": ["B"]}
    return spec, problems


# ---------------------------------------------------------------- one turn's script and the search over its unknowns

class TurnScript:
    """What each seat must do in one turn. Everything the record leaves open is a choice point: when to cast each
    recorded play (now or wait), which pairing of blockers, which target, mode, "may" answer, trigger order. Each
    choice point lists its alternatives, the likeliest first. `path` fixes the alternative at the first len(path)
    choice points; later ones take their first alternative. The driver searches over paths (fewest departures from
    the first alternatives first) and rewinds the turn between attempts."""

    def __init__(self, rec: Record, t: int, path: tuple, names: Names, state: dict | None = None):
        self.t, self.path, self.names = t, path, names
        self.active, self.prefix = rec.slot(t)
        self.other = "B" if self.active == "A" else "A"
        p = rec.plays(self.prefix, self.active)
        self.p = p
        self.todo = {s: {"lands": collections.Counter(p[s].get("lands", [])), "spells": collections.Counter(p[s].get("spells", [])),
                         "attack": collections.Counter(p[s].get("attack", [])),
                         "abilities": collections.Counter(a for a in (names.ability(x) for x in p[s].get("abilities", [])) if a)}
                     for s in ("A", "B")}
        self.expected = rec.expected(self.prefix)
        self.killed = collections.Counter(p["killed"])
        self.noncreature = collections.Counter(p["noncreature_cast"])
        self.tutored = collections.Counter(rec.L(self.prefix, "cards_tutored"))
        # what each seat ends the turn with: a choice that brings one of these in (a search, a manifest) is likelier
        self.gain = {"A": collections.Counter(self.expected["bf_A"] + self.expected["hand_A"]), "B": collections.Counter(self.expected["bf_B"])}
        self.pairings = block_pairings(p[self.other]["block"], p["blocked"])
        self.pairing = None
        self.flash_blockers = set(p[self.other].get("flash", [])) & {names.norm(x) for x in p[self.other]["block"]}
        # which door of a Room each seat cast: 17lands records the door, so cast that one, not the other
        self.halves = {s_: collections.Counter() for s_ in ("A", "B")}
        for raw in names.raw_names(rec.r.get(self.prefix + "non_creatures_cast")):
            if raw in names.half_of:
                self.halves[self.active][raw] += 1
        # A's casts this turn that weren't in its hand or drawn: played from exile (a Room door like Painter's Studio
        # exiles the top cards to play). Stacked on top of the library before such an effect.
        self.from_elsewhere = []
        if state is not None and self.active == "A":
            have = collections.Counter(names.norm(c) for c in state["A"]["hand"]) + collections.Counter(rec.L(self.prefix, "cards_drawn"))
            self.from_elsewhere = sorted((collections.Counter(p["A"]["spells"]) - have).elements())
        self.taken, self.alts, self.points = [], [], []
        self.offered = set()   # (seat, kind, name) of recorded plays XMage offered at some point this attempt
        self.unlocks = 0
        self.unscripted = []
        if +self.todo["A"]["abilities"] or +self.todo["B"]["abilities"]:
            self.unscripted.append("activated_abilities")

    def choose(self, n: int, what: str) -> int:
        """Index of the alternative to take at the next choice point with n alternatives."""
        if n < 2:
            return 0
        i = len(self.taken)
        c = self.path[i] if i < len(self.path) and self.path[i] < n else 0
        self.taken.append(c)
        self.alts.append(n)
        self.points.append(what)
        return c

    def remaining(self) -> dict:
        out = {}
        for s in ("A", "B"):
            for k, c in self.todo[s].items():
                if +c:
                    out[f"{s}:{k}"] = sorted(str(x) if not isinstance(x, tuple) else str(x[0] or x[1][:20]) for x in (+c).elements())
        if self.pairing is not None and +self.block_todo:
            out[f"{self.other}:block"] = sorted(f"{b}>{a}" for b, a in (+self.block_todo).elements())
        elif self.pairing is None and self.pairings:
            out[f"{self.other}:block"] = ["no block declared"]
        return out


def block_pairings(blockers: list[str], blocked: list[str], cap: int = 8, budget: int = 20_000) -> list[list[tuple[str, str]]]:
    """Ways to give each recorded blocker one of the blocked attackers, every blocked attacker getting at least one.

    The search walks every assignment in order, which is attackers ** blockers of them: with many blocks the first one
    that covers every attacker can be astronomically far in. Row 499338 recorded 14 blockers on 14 attackers (14**14)
    and spun for 41 hours. So the walk stops after `budget` assignments, and if it found nothing, one pairing that
    covers every attacker is built directly."""
    if not blockers or not blocked:
        return []
    att, bl = sorted(set(blocked)), sorted(blockers)
    out = []
    for i, combo in enumerate(itertools.product(att, repeat=len(bl))):
        if len(out) >= cap or i >= budget:
            break
        if set(combo) >= set(blocked):
            pairs = sorted(zip(bl, combo))
            if pairs not in out:
                out.append(pairs)
    if not out and len(bl) >= len(att):
        out.append(sorted(zip(bl, att + [att[i % len(att)] for i in range(len(bl) - len(att))])))
    return out or [sorted(zip(bl, sorted(blocked)))]


# ---------------------------------------------------------------- answering decisions

def entry_name(msg: dict, ref: dict, hidden_as_face_down: bool = False) -> str | None:
    """Card name of an option's source or target. With hidden_as_face_down, a face-down permanent is
    "[Face-Down Card]", as 17lands records the opponent's (and its own player sees the real name)."""
    i = (ref or {}).get("entry")
    if i is None:
        return None
    e = msg["obs"]["entries"][i]
    if hidden_as_face_down and e.get("face_down"):
        return FACE_DOWN
    n = e.get("card_name") or e.get("name") or ""
    return n.split(": ", 1)[1] if n.startswith(("Manifest: ", "Cloak: ")) else n


# the other player's instants: when they are most often cast, first
OTHER_WINDOWS = ("DECLARE_BLOCKERS", "END_TURN", "DECLARE_ATTACKERS", "BEGIN_COMBAT", "PRECOMBAT_MAIN", "UPKEEP")


def priority_alternatives(msg, sc: TurnScript, names: Names) -> list:
    """The recorded plays this seat could make now, in likeliest order, with "wait" (None) where waiting is possible."""
    seat, step, opts = msg["seat"], msg["step"], msg["options"]
    todo = sc.todo[seat]
    active = seat == sc.active
    items = []   # (option index, kind, key)
    seen = set()
    for i, o in enumerate(opts):
        parts = o["label"].split(" | ")
        if len(parts) < 2:
            continue
        name = names.norm(parts[1])
        if o["action"] == "PLAY_LAND" and active and todo["lands"][name] > 0:
            key = ("lands", name)
        elif o["action"] == "CAST" and todo["spells"][name] > 0:
            raw = parts[1].strip()
            wanted = {h: k for h, k in sc.halves[seat].items() if names.half_of[h][0] == name and k > 0}
            if raw in names.half_of and wanted and raw not in wanted:
                continue   # the other door of a Room whose recorded door is still to cast
            key = ("spells", name)
        elif o["action"] == "ACTIVATE" and len(parts) >= 3:
            text = norm_text(parts[2].replace(parts[1], "{this}"))
            key = next((("abilities", (c, t)) for (c, t), k in todo["abilities"].items()
                        if k > 0 and (c is None or c == name) and (t[:25] in text or text[:25] in t)), None)
            if key is None:
                continue
        else:
            continue
        if key not in seen:
            seen.add(key)
            items.append((i, key))
            sc.offered.add((seat,) + key[:1] + (str(key[1]),))
    if not items and not (active and step in ("PRECOMBAT_MAIN", "POSTCOMBAT_MAIN") and sc.unlocks < 2
                          and any(o["action"] == "SPECIAL" and "Unlock" in o["label"] for o in opts)):
        return []
    # sorted by kind and name, never by XMage's option order (it follows object ids, which differ between runs)
    items.sort(key=lambda it: ({"lands": 0, "spells": 1, "abilities": 2}[it[1][0]], str(it[1][1])))
    last_chance = step == "END_TURN" or active and step == "POSTCOMBAT_MAIN" and all(k[0] == "lands" for _, k in items)
    if active:
        now = step in ("PRECOMBAT_MAIN", "POSTCOMBAT_MAIN")
    else:
        now = step in ("DECLARE_BLOCKERS", "END_TURN") or step == "DECLARE_ATTACKERS" and any(k[1] in sc.flash_blockers for _, k in items)
    alts = list(items)
    if not last_chance:
        alts = alts + [None] if now else [None] + alts
    # unlocking a Room door is a special action 17lands doesn't record: try it only after the recorded reading,
    # never as the default, and at most twice a turn
    if active and step in ("PRECOMBAT_MAIN", "POSTCOMBAT_MAIN") and sc.unlocks < 2:
        unlocks = sorted((o["label"], i) for i, o in enumerate(opts) if o["action"] == "SPECIAL" and "Unlock" in o["label"])
        if unlocks and None not in alts:
            alts.append(None)
        alts += [(i, ("unlock", lab)) for lab, i in unlocks]
    return alts


def answer(msg: dict, sc: TurnScript | None, rec: Record, names: Names) -> int:
    seat, kind, prompt, opts = msg["seat"], msg["kind"], msg["prompt"], msg["options"]
    labels = [o["label"] for o in opts]
    if kind == "USE" and prompt.startswith("Mulligan"):
        want = int(rec.r["num_mulligans"] or 0) if seat == "A" else int(rec.r["opp_num_mulligans"] or 0)
        mull = MULLIGANS[seat] < want
        if mull:
            MULLIGANS[seat] += 1
        return pick(labels, "YES" if mull else "NO")
    if "bottom of your library" in prompt:
        if seat == "A":
            hands = rec.hands_a()
            kept, opening = hands[-1] if hands else [], collections.Counter(names.names(rec.r.get("opening_hand")))
            bottom = collections.Counter(kept) - opening
            for i in sorted(range(len(opts)), key=lambda i: opts[i]["label"]):
                if bottom[opts[i]["label"]] > 0:
                    return i
        # B: bottom the card it needs last (or never): its draws are a queue of what it needs, in order
        seq = rec.b_sequence()
        first = lambda n: seq.index(n) if n in seq else len(seq)
        return max(range(len(opts)), key=lambda i: (first(opts[i]["label"]), opts[i]["label"]))
    if sc is None:
        return 0
    todo = sc.todo[seat]
    by_label = sorted(range(len(opts)), key=lambda i: (labels[i], i))   # run-independent order
    if kind == "PRIORITY":
        alts = priority_alternatives(msg, sc, names)
        if not alts:
            return pick(labels, "PASS")
        c = alts[sc.choose(len(alts), f"{seat} {msg['step']} play")]
        if c is None:
            return pick(labels, "PASS")
        i, (k, key) = c
        if k == "unlock":
            sc.unlocks += 1
            card = names.norm((opts[i]["label"].split(" | ") + ["", ""])[1])
            if seat == "A" and sc.from_elsewhere and "exile the top" in names.rules.get(card, names.rules.get(names.full.get(card, ""), "")).lower():
                EXTRA["top"] = {"A": sc.from_elsewhere}
            return i
        todo[k][key] -= 1
        raw = (opts[i]["label"].split(" | ") + ["", ""])[1].strip()
        if k == "spells" and sc.halves[seat][raw] > 0:
            sc.halves[seat][raw] -= 1
        card = key[0] if k == "abilities" else key
        if seat == "A" and card and "manifest dread" in names.rules.get(card, "").lower():
            # manifest dread looks at the top two cards: put the card A ends the turn with face down on top
            mine = collections.Counter(names.norm(e.get("card_name") or e.get("name") or "").split(": ", 1)[-1]
                                       for e in msg["obs"]["entries"] if e.get("zone") == "BATTLEFIELD" and e.get("mine"))
            pending = collections.Counter(todo["lands"]) + collections.Counter(todo["spells"])
            fate = sorted((collections.Counter(sc.expected["bf_A"]) - mine - pending).elements())
            if fate:
                EXTRA["top"] = {"A": fate[:1]}
        return i
    if kind == "ATTACK":
        for i, o in enumerate(opts):
            n = entry_name(msg, o["source"], hidden_as_face_down=seat == "B")
            if o["action"] == "ATTACK" and n and todo["attack"][names.norm(n)] > 0:
                todo["attack"][names.norm(n)] -= 1
                return i
        return pick(labels, "DONE")
    if kind == "BLOCK":
        if sc.pairing is None:
            sc.pairing = sc.pairings[sc.choose(len(sc.pairings), "block pairing")] if sc.pairings else []
            sc.block_todo = collections.Counter(sc.pairing)
        for i, o in enumerate(opts):
            if o["action"] != "BLOCK":
                continue
            b = names.norm(entry_name(msg, o["source"], hidden_as_face_down=seat == "B") or "")
            a = names.norm(entry_name(msg, o["target"], hidden_as_face_down=seat == "A") or "")
            if sc.block_todo[(b, a)] > 0:
                sc.block_todo[(b, a)] -= 1
                return i
        return pick(labels, "DONE")
    if kind == "CHOICE":
        keys = [o.get("choice_key") or "" for o in opts]
        if any(k.startswith("alt_cost") for k in keys):
            # Impending (Overlords): cast as a non-creature, so 17lands lists it under non-creature casts
            src = [entry_name(msg, o["source"]) for o in opts]
            impending = any(sc.noncreature[names.norm(s or "")] > 0 for s in src)
            for i, k in enumerate(keys):
                if (k == "alt_cost:ImpendingAbility") == impending and k.startswith("alt_cost"):
                    return i
        return by_label[sc.choose(min(3, len(opts)), f"{seat} choice")]
    if kind == "USE":
        order = [pick(labels, "YES"), pick(labels, "NO")]
        return order[sc.choose(2, f"{seat} may")]
    if kind == "MODE" or kind == "TRIGGER_ORDER":
        return by_label[sc.choose(min(3, len(opts)), f"{seat} {kind.lower()}")]
    if kind in ("TARGET", "CHOOSE", "TARGET_CARDS", "CHOOSE_CARDS"):
        if "Surveil" in prompt or "Scry" in prompt:
            EXTRA["_label"] = "not_recorded"   # our fixed answer, not the player's: 17lands doesn't record it
            return pick(labels, "DONE")  # keep the top of the library: the recorded draws come from the queue anyway
        order = list(by_label)
        # what this seat still lacks compared with its recorded end of turn (board, and hand for A)
        have = collections.Counter(names.norm((e.get("card_name") or e.get("name") or "").split(": ", 1)[-1])
                                   for e in msg["obs"]["entries"] if e.get("mine") and e.get("zone") in ("BATTLEFIELD", "HAND"))
        deficit = sc.gain[seat] - have
        def rank(i):
            o = opts[i]
            n = names.norm(entry_name(msg, o["target"]) or o["label"])
            if sc.tutored[n] > 0:
                return 0
            if sc.killed[n] > 0:
                return 1
            if deficit[n] > 0 and kind in ("CHOOSE_CARDS", "TARGET_CARDS", "CHOOSE"):
                return 2
            if (o.get("target") or {}).get("player") == "opp":
                return 3
            return 5 if o["label"] == "DONE" else 4
        order.sort(key=rank)
        return order[sc.choose(min(4, len(order)), f"{seat} target")]
    return 0


def pick(labels: list[str], want: str) -> int:
    for i, l in enumerate(labels):
        if l.strip().upper().startswith(want):
            return i
    return 0


MULLIGANS = {"A": 0, "B": 0}
EXTRA = {}   # fields answer() adds to its reply (e.g. "top")
RESIDUAL = collections.Counter()


# ---------------------------------------------------------------- comparison

def observed(state: dict, names: Names) -> dict:
    def bf(seat, hide_face_down):
        out = []
        for p in state[seat]["battlefield"]:
            out.append(FACE_DOWN if hide_face_down and p["face_down"] else names.norm(p["name"]))
        return sorted(out)
    return {"life_A": state["A"]["life"], "life_B": state["B"]["life"], "hand_A": sorted(names.norm(c) for c in state["A"]["hand"]),
            "hand_B": len(state["B"]["hand"]), "bf_A": bf("A", False), "bf_B": bf("B", True)}


def diff(exp: dict, obs: dict) -> dict:
    out = {}
    for k in exp:
        e, o = exp[k], obs[k]
        if e is None:
            continue
        if isinstance(e, list):
            ce, co = collections.Counter(e), collections.Counter(o)
            if ce != co:
                out[k] = {"missing": sorted((ce - co).elements()), "extra": sorted((co - ce).elements())}
        elif e != o:
            out[k] = {"expected": e, "got": o}
    return out


# ---------------------------------------------------------------- the driver

def _write_sample(seed: int, games: int, path: str, sample: int = 0, offset: int = 0, exclude: str = ""):
    lf = pl.scan_parquet(DATA / "parquet/replay_data.parquet")
    n = lf.select(pl.len()).collect().item()
    skip = {int(x) for x in Path(exclude).read_text().split()} if exclude else set()
    pool = [i for i in range(n) if i not in skip] if skip else range(n)
    rows_idx = sorted(random.Random(seed).sample(pool, sample or games))[offset:offset + games]
    lf.with_row_index("row").filter(pl.col("row").is_in(rows_idx)).collect().write_parquet(path)


def sampled_rows(seed: int, games: int, path: Path, sample: int = 0, offset: int = 0, exclude: str = "") -> pl.DataFrame:
    """The sampled games, picked in a short-lived child process. Picking rows out of the 1M-game file makes polars
    decode every column of the row groups it reads, about 8 GB for a moment, and the process keeps ~5 GB of that after.
    Four workers each holding that hung the mini on 2026-10-28. The child exits once the few hundred rows are written,
    which returns the memory, and a lock lets only one worker pick at a time."""
    import fcntl, multiprocessing
    with open(DATA / "turn_replay" / ".sample.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        p = multiprocessing.get_context("spawn").Process(target=_write_sample, args=(seed, games, str(path), sample, offset, exclude))
        p.start()
        p.join()
    if p.exitcode != 0:
        sys.exit(f"picking the sample failed (exit code {p.exitcode})")
    return pl.read_parquet(path)


def run(args):
    names = Names()
    out = DATA / "turn_replay" / args.run
    (out / "decks").mkdir(parents=True, exist_ok=True)
    df = sampled_rows(args.seed, args.games, out / "sample.parquet", args.sample, args.offset, args.exclude)
    recs, specs, skipped = {}, [], {}
    for row in df.iter_rows(named=True):
        rec = Record(row, names)
        gid = f"g{row['row']}"
        spec, problems = game_spec(rec, names, out / "decks", gid)
        if problems:
            skipped[gid] = problems
            continue
        recs[gid] = rec
        specs.append(spec)
    (out / "games.jsonl").write_text("".join(json.dumps(s) + "\n" for s in specs))
    cp = ":".join([args.classes] + sorted(glob.glob(str(RUNTIME / "**/*.jar"), recursive=True)))

    def open_jvm(k: int, chunk: list):
        """One JVM per chunk of games: XMage keeps per-game state around, so a long run in one JVM runs out of heap.

        A JVM that exits before connecting is started again, up to 3 tries: when two workers start XMage at the same
        moment, one can fail to open XMage's card database and die (4 of 100 batches in the 50k run)."""
        path = out / f"games_{k:03d}.jsonl"
        path.write_text("".join(json.dumps(sp) + "\n" for sp in chunk))
        log = out / f"jvm_{k:03d}.log"
        for attempt in range(3):
            if attempt:
                log.rename(log.with_suffix(f".failed{attempt}.log"))
                time.sleep(random.uniform(5, 20))
            srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
            jvm = subprocess.Popen(["java", "-Xmx4g", "-Djava.awt.headless=true", "--add-opens=java.base/java.lang=ALL-UNNAMED", "-cp", cp,
                                    "ReplayMatch", str(srv.getsockname()[1]), str(path)],
                                   cwd=RUNTIME, stdout=open(log, "w"), stderr=subprocess.STDOUT)
            srv.settimeout(5)
            conn = None
            for _ in range(60):   # up to 300 s, as before, but give up as soon as the JVM has exited
                try:
                    conn, _ = srv.accept()
                    break
                except TimeoutError:
                    if jvm.poll() is not None:
                        break
            srv.close()
            if conn:
                break
            jvm.kill()
        else:
            raise RuntimeError(f"XMage did not start for chunk {k} after 3 tries, see {log}")
        conn.settimeout(300)
        return jvm, conn.makefile("rw")

    def lines():
        for k in range(0, len(specs), args.chunk):
            jvm, f = open_jvm(k // args.chunk, specs[k:k + args.chunk])
            CHAN["f"], CHAN["jvm"] = f, jvm
            for line in f:
                yield line
                if json.loads(line)["type"] == "end":
                    break
            jvm.wait(timeout=60)

    CHAN = {}
    log = open(out / "turns.jsonl", "w")
    gi = 0
    cur = {"gid": None}
    stats = collections.Counter()

    by_id = {sp["id"]: sp for sp in specs}

    def new_game(gid=None):
        nonlocal gi
        spec = by_id[gid] if gid else specs[gi]; gi += 1
        MULLIGANS["A"] = MULLIGANS["B"] = 0
        cur.update(gid=spec["id"], rec=recs[spec["id"]], sc=None, t=None, path=(), frontier=[], seen=set(), best=None,
                   failed=False, attempts=0, fixed_to=None, fix_sent=None, game_attempts=0)

    new_game()

    def draws_for(t: int, state: dict) -> dict:
        rec = cur["rec"]
        a = rec.a_draws_by_turn()
        future = []
        for u in range(t, 2 * rec.turns + 2):
            future += a.get(u, [])
        # B: what it still has to play from this turn on, minus what is already in its hand
        need = []
        for u in range(t, 2 * rec.turns + 2):
            s = rec.slot(u)
            if s:
                b = rec.plays(s[1], s[0])["B"]
                need += b.get("lands", []) + b.get("spells", [])
        in_hand = collections.Counter(names.norm(c) for c in state["B"]["hand"])
        queue = []
        for c in need:
            if c not in names.code:
                continue
            if in_hand[c] > 0:
                in_hand[c] -= 1   # already holds it: don't draw another copy
            else:
                queue.append(c)
        return {"A": future, "B": queue}

    rows_out = gzip.open(out / "decisions.jsonl.gz", "wt") if args.rows else None

    def write_row(row: dict, label: str, turn: int):
        """One decision of the user's seat, for training: what it saw, its options, what it chose, and how sure that is."""
        rec = cur["rec"]
        rows_out.write(json.dumps({"game": cur["gid"], "draft_id": rec.r["draft_id"], "turn": turn, "label": label,
                                   "seat": "A", **row}) + "\n")
        stats[f"rows_{label}"] += 1

    def finish_turn(ok: bool, d: dict, extra: dict):
        last = cur["rec"].slot(cur["t"] + 1) is None
        rec = {"game": cur["gid"], "turn": cur["t"], "active": cur["sc"].active, "prefix": cur["sc"].prefix, "ok": ok, "last": last,
               "start_exact": not cur["failed"] or cur.get("start_exact", False),
               "attempts": cur["attempts"], "after_resync": cur["failed"], "diff": d, "unscripted": cur["sc"].unscripted, **extra}
        log.write(json.dumps(rec) + "\n"); log.flush()
        if last:   # the game's final turn: often a concession, which no play reproduces; counted on its own
            stats["last_turns"] += 1
            stats["last_ok"] += ok
            return
        if ok and args.rows and not cur["failed"]:
            amb = {i: x["ambiguous"] for i, x in enumerate(extra.get("ambiguity") or [])}
            for row in cur.get("buf", []):
                if row.pop("fixed_label", None):
                    label = "not_recorded"        # an answer the replay fixes itself (surveil, scry)
                elif row["point"] is None:
                    label = "recorded"            # the record decides it (attacks, blocks, the only legal reading)
                elif row["point"] in amb:
                    label = "ambiguous" if amb[row["point"]] else "unique"
                else:
                    label = "unprobed"            # searched, and no ambiguity check ran
                write_row(row, label=label, turn=cur["t"])
        key = "after_resync" if cur["failed"] else "clean"
        cur["last_ok"] = ok
        if not ok:
            cur["start_exact"] = False
        stats["exact_start_turns"] += rec["start_exact"]
        stats["exact_start_ok"] += rec["start_exact"] and ok
        stats[f"{key}_turns"] += 1
        stats[f"{key}_ok"] += ok
        if not ok:
            cur["failed"] = True
        if args.verbose:
            print(f"{cur['gid']} t{cur['t']} {cur['sc'].active} {'OK' if ok else 'FAIL'} after {cur['attempts']} {'' if ok else json.dumps(d)[:300]}", flush=True)

    class Stalled(Exception):
        pass

    def on_alarm(*_):
        raise Stalled()

    def handle(line):
        f = CHAN["f"]
        msg = json.loads(line)
        if msg.get("game") and msg["game"] != cur["gid"]:
            # a JVM that died mid-chunk skips games: follow the id XMage reports, not our count
            stats["games_lost"] += 1
            new_game(msg["game"])
        typ = msg["type"]
        reply = {"choice": 0}
        if args.trace and f"{cur['gid']}:{msg.get('turn')}" == args.trace and typ in ("turn_start", "eot"):
            print(f"  == {typ} rollbacks={msg.get('rollbacks')} A bf={sorted(p['name'] for p in msg['state']['A']['battlefield'])} "
                  f"B bf={sorted(p['name'] for p in msg['state']['B']['battlefield'])} B hand={msg['state']['B']['hand']}")
        if typ == "turn_start":
            t = msg["turn"]
            rec = cur["rec"]
            if cur.get("fixed_to") is not None and cur["t"] != t:
                # how well the last resync took: the state at this turn's start against the record it was reset to
                residual = diff(cur["fixed_to"], observed(msg["state"], names))
                cur["residual"] = residual
                cur["start_exact"] = not residual
                if os.environ.get("DEBUG_RESIDUAL") and "bf_A" in residual:
                    print("RESIDUAL", cur["gid"], t, json.dumps(residual), "| fix A bf:", sorted(cur["fix_sent"]["A"]["battlefield"]),
                          "| state A bf:", sorted(p["name"] for p in msg["state"]["A"]["battlefield"]),
                          "| A hand:", sorted(msg["state"]["A"]["hand"]), "| A gy:", sorted(msg["state"]["A"]["graveyard"]), "| lib", msg["state"]["A"]["library"])
                stats["resyncs"] += 1
                stats["resyncs_exact"] += not residual
                for k, v in residual.items():
                    stats[f"resync_residual_{k}"] += 1
                    if isinstance(v, dict) and "missing" in v:
                        for n in v["missing"]: RESIDUAL[f"{k} missing {n}"] += 1
                        for n in v["extra"]: RESIDUAL[f"{k} extra {n}"] += 1
                cur["fixed_to"] = None
            if rec.slot(t) is None:
                cur["sc"] = None
                if t > 1:
                    # the record has run out (most games end in a concession, which no play reproduces): end the game
                    # the way it ended, with the 17lands loser conceding, instead of playing on to a deck-out
                    reply["concede"] = "B" if rec.r.get("won") else "A"
                    stats["games_conceded"] += 1
            else:
                if cur["t"] != t:
                    cur.update(t=t, path=(), frontier=[], seen={()}, attempts=0, best=None, probe=None)
                if cur.get("fixed_to") is None and cur["failed"] and cur.get("last_ok"):
                    cur["start_exact"] = True   # the previous turn reproduced, so this one starts from the record too
                cur["attempts"] += 1
                cur["buf"] = []
                cur["sc"] = TurnScript(rec, t, cur["path"], names, msg["state"])
            reply["draws"] = draws_for(t, msg["state"])
        elif typ == "eot":
            sc = cur["sc"]
            if sc is not None:
                obs = observed(msg["state"], names)
                d = diff(sc.expected, obs)
                rem = sc.remaining()
                if rem:
                    d["not_done"] = rem
                    never = sorted(f"{s_}:{k}:{n}" for s_ in ("A", "B") for k in ("lands", "spells", "abilities")
                                   for n_, c in sc.todo[s_][k].items() if c > 0 for n in [str(n_[0] or n_[1][:20]) if isinstance(n_, tuple) else n_]
                                   if (s_, k, str(n_)) not in sc.offered)
                    if never:
                        d["never_offered"] = never
                score = len(d)
                if cur["best"] is None or score < cur["best"][0]:
                    cur["best"] = (score, d)
                probe = cur.get("probe")
                if probe is not None:
                    # ambiguity check: did this departure from the reproducing choices also reproduce the turn?
                    if probe["at"] is not None:
                        probe["results"].append((probe["at"][0], probe["at"][1], not d))
                    if probe["queue"]:
                        j, a = probe["queue"].pop(0)
                        probe["at"] = (j, a)
                        cur["path"] = tuple(probe["good"][:j]) + (a,)
                        reply["rollback"] = True
                    elif probe["at"] is not None:
                        probe["at"] = None          # replay the reproducing choices once more, then move on
                        cur["path"] = tuple(probe["good"])
                        reply["rollback"] = True
                    else:
                        amb = collections.defaultdict(lambda: [0, 0])   # kind -> [points, ambiguous points]
                        hit = {j for j, a, ok in probe["results"] if ok}
                        rows = []
                        for j, (what, n) in enumerate(zip(probe["points"], probe["alts"])):
                            w = what.split()
                            kind = "block pairing" if what.startswith("block") else f"{w[0]} {w[-1]}"   # seat + kind
                            amb[kind][0] += 1
                            amb[kind][1] += j in hit
                            rows.append({"point": what, "alternatives": n, "ambiguous": j in hit,
                                         "fully_probed": all((j, a) in {(x, y) for x, y, _ in probe["results"]} for a in range(n) if a != probe["good"][j])})
                        for k, (n, m) in amb.items():
                            stats[f"amb_points_{k}"] += n
                            stats[f"amb_ambiguous_{k}"] += m
                        cur["probe"] = None
                        finish_turn(not d, {} if not d else d, {"path": list(probe["good"]), "points": len(probe["good"]),
                                                               "ambiguity": rows, "probe_final_matched": not d})
                elif not d and args.probe and not cur["failed"] and sc.taken:
                    queue = [(j, a) for j in range(len(sc.taken)) for a in range(sc.alts[j]) if a != sc.taken[j]][:args.probe]
                    cur["probe"] = {"good": list(sc.taken), "alts": list(sc.alts), "points": list(sc.points),
                                    "queue": queue, "results": [], "at": None}
                    j, a = queue.pop(0)
                    cur["probe"]["at"] = (j, a)
                    cur["path"] = tuple(sc.taken[:j]) + (a,)
                    reply["rollback"] = True
                elif not d:
                    finish_turn(True, {}, {"path": list(sc.taken), "points": len(sc.taken)})
                else:
                    # children: depart from what this attempt took at one later choice point
                    for j in range(len(cur["path"]), len(sc.taken)):
                        for a in range(sc.alts[j]):
                            child = tuple(sc.taken[:j]) + (a,)
                            if a != sc.taken[j] and child not in cur["seen"]:
                                cur["seen"].add(child)
                                heapq.heappush(cur["frontier"], (sum(1 for x in child if x), len(child), child))
                    cur["game_attempts"] = cur.get("game_attempts", 0) + 1
                    if cur["frontier"] and cur["attempts"] < args.budget and cur["game_attempts"] < args.game_budget:
                        cur["path"] = heapq.heappop(cur["frontier"])[2]
                        reply["rollback"] = True
                    else:
                        finish_turn(False, cur["best"][1], {"points": len(sc.taken), "exhausted": not cur["frontier"]})
                        reply["fix"] = cur["rec"].fix(sc.prefix)
                        cur["fixed_to"] = sc.expected
                        cur["fix_sent"] = reply["fix"]
                    # carry on from this attempt: the game no longer matches the record
        elif typ == "decision":
            try:
                EXTRA.clear()
                sc_ = cur["sc"]
                before = len(sc_.taken) if sc_ is not None else 0
                reply["choice"] = answer(msg, cur["sc"], cur["rec"], names)
                fixed_label = EXTRA.pop("_label", None)
                reply.update(EXTRA)
                if args.rows and msg["seat"] == "A":
                    point = before if sc_ is not None and len(sc_.taken) > before else None
                    row = {"kind": msg["kind"], "prompt": msg["prompt"], "step": msg.get("step"), "obs": msg["obs"],
                           "options": msg["options"], "choice": reply["choice"], "point": point, "fixed_label": fixed_label}
                    if sc_ is None and cur["t"] is None:   # mulligans and bottoms, before turn 1: recorded exactly
                        row.pop("fixed_label", None)
                        write_row(row, label="recorded", turn=0)
                    elif sc_ is None:
                        # Past the record (its last turn, or the 30-turn cap): XMage plays on, often to a deck-out,
                        # since the real ending (usually a concession) isn't reproduced, and every answer is a default.
                        # These used to be written as "recorded" turn-0 rows: ~84% of the recorded rows in dsk50k.
                        stats["decisions_past_record"] += 1
                    else:
                        cur.setdefault("buf", []).append(row)
            except Exception as e:  # a bug in the script must not hang the JVM
                print("answer error", cur["gid"], msg.get("kind"), repr(e), file=sys.stderr)
                reply["choice"] = 0
            if args.trace and f"{cur['gid']}:{msg.get('turn')}" == args.trace:
                print(f"  [{msg['seat']} {msg['step']} a{cur['attempts']}] {msg['kind']} {msg['prompt'][:60]!r} -> "
                      f"{msg['options'][reply['choice']]['label'][:70]!r}   of {[o['label'][:40] for o in msg['options']][:8]}")
        elif typ == "game_end":
            sc = cur["sc"]
            if sc is not None and cur["t"] is not None:
                # the game ended inside a turn (lethal): compare what we can
                obs = observed(msg["state"], names)
                d = diff(sc.expected, obs)
                last = cur["rec"].slot(cur["t"] + 1) is None
                stats["games_ended_in_turn"] += 1
            stats["games"] += 1
            if msg.get("error"):
                stats["games_with_error"] += 1
            f.write("{}\n"); f.flush()
            if gi < len(specs):
                new_game()
            return
        elif typ == "end":
            return
        f.write(json.dumps(reply) + "\n"); f.flush()

    def finish():
        if rows_out:
            rows_out.close()
        summary = {"games": len(specs), "skipped": skipped, "budget": args.budget, "seconds": round(time.time() - t0, 1), **stats}
        if stats["exact_start_turns"]:
            summary["exact_start_rate"] = round(stats["exact_start_ok"] / stats["exact_start_turns"], 3)
        for k in ("clean", "after_resync"):
            if stats[f"{k}_turns"]:
                summary[f"{k}_rate"] = round(stats[f"{k}_ok"] / stats[f"{k}_turns"], 3)
        summary["resync_residual_top"] = RESIDUAL.most_common(25)
        (out / "summary.json").write_text(json.dumps(summary, indent=1))
        print(json.dumps(summary, indent=1))

    # A reply that takes longer than --stall seconds is a stall: in the second 50k run one batch spun in Python for
    # 41 hours on one game. The rest of that JVM's chunk is given up (its games count as lost) and the run goes on.
    signal.signal(signal.SIGALRM, on_alarm)
    t0 = time.time()
    for line in lines():
        signal.alarm(args.stall)
        try:
            handle(line)
        except Stalled:
            stats["stalls"] += 1
            print(f"stalled on {cur['gid']} turn {cur['t']}: giving up the rest of this chunk", flush=True)
            CHAN["jvm"].kill()
        finally:
            signal.alarm(0)
    finish()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--sample", type=int, default=0,
                    help="draw this many games with --seed (default --games) and replay --games of them from --offset, "
                         "so batches of one sample never overlap (see replay_batches.py)")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--stall", type=int, default=600, help="seconds one reply may take before the chunk is given up")
    ap.add_argument("--exclude", default="", help="a file of replay_data row numbers never to pick (games already replayed)")
    ap.add_argument("--budget", type=int, default=40, help="attempts per turn")
    ap.add_argument("--chunk", type=int, default=10, help="games per JVM")
    ap.add_argument("--game-budget", type=int, default=400, help="rewinds per game, at most")
    ap.add_argument("--rows", action="store_true",
                    help="write the user's decisions in clean, reproduced turns to decisions.jsonl.gz, each labelled "
                         "recorded / unique / ambiguous / unprobed / not_recorded")
    ap.add_argument("--probe", type=int, default=0,
                    help="ambiguity check: after a clean turn reproduces, try up to this many other choices to see if they fit too")
    ap.add_argument("--run", default=time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--classes", default="/tmp/xmage-cls-dev")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--trace", help="print every decision of one turn, e.g. g403958:5")
    run(ap.parse_args())
