"""Facts the harness computes from a seat's own observation, shown to the Claude player under "Facts:" (--facts-a/b).

Reviewed games showed the same few slips again and again: believing attackers untap before the opponent's turn,
believing mana spent now comes back for the opponent's turn, and combat arithmetic (first strike, double blocks
whose damage splits exactly, how much gets through next turn). These lines state those things for the board as it
is. They use only the seat's own observation (no hidden information) and ignore everything not on the board: tricks,
flash creatures, face-down creatures being turned up, and abilities that aren't listed keywords ("can't block").
"""
import re
from functools import lru_cache

from render import load_card_text

BASIC_COLOR = {"Plains": "W", "Island": "U", "Swamp": "B", "Mountain": "R", "Forest": "G", "Everywhere": "WUBRG"}
MAIN_STEPS = ("Upkeep", "Draw", "Precombat Main", "Begin Combat", "Declare Attackers", "Postcombat Main")

CAVEAT = ("board only, plus pump tricks in your own hand and a list of tricks the opponent could have: the outcomes "
          "ignore opponent tricks, flash, face-down flips and unlisted abilities")

# DSK's common and uncommon instant-speed cards that change a fight, checked against the set's card data
# (2026-11-01): (name, cost, what it does, kind). Kinds order the list: what turns a block around first.
OPP_TRICKS = [
    ("Horrid Vigor", "{1}{G}", "deathtouch + indestructible", "deathtouch"),
    ("Jump Scare", "{W}", "+2/+2 and flying", "pump"),
    ("Turn Inside Out", "{R}", "+3/+0", "pump"),
    ("Violent Urge", "{R}", "+1/+0 and first strike", "pump"),
    ("Shardmage's Rescue", "{W}", "flash aura on their creature: +1/+1, hexproof", "pump"),
    ("Give In to Violence", "{1}{B}", "+2/+2 and lifelink", "pump"),
    ("Frantic Strength", "{2}{G}", "flash aura: +2/+2 and trample", "pump"),
    ("Unwanted Remake", "{W}", "destroy target creature", "removal"),
    ("Nowhere to Run", "{1}{B}", "flash: -3/-3", "removal"),
    ("Winter's Intervention", "{1}{B}", "2 damage", "removal"),
    ("Scorching Dragonfire", "{1}{R}", "3 damage", "removal"),
    ("Seized from Slumber", "{1}{W}", "destroy target tapped creature ({4}{W} otherwise)", "removal"),
    ("Murder", "{1}{B}{B}", "destroy target creature", "removal"),
    ("Withering Torment", "{2}{B}", "destroy target creature", "removal"),
    ("Betrayer's Bargain", "{1}{R}", "5 damage (plus {2} or a sacrifice)", "removal"),
    ("Floodpits Drowner", "{1}{U}", "flash creature: taps a creature and stuns it", "flash"),
    ("Appendage Amalgam", "{2}{B}", "flash 3/2 creature (a surprise blocker)", "flash"),
    ("Untimely Malfunction", "{1}{R}", "one or two creatures can't block", "flash"),
    ("Drag to the Roots", "{2}{B}{G}", "destroy target nonland permanent ({B}{G} with delirium)", "removal"),
    ("Live or Die", "{3}{B}{B}", "destroy target creature", "removal"),
    ("Impossible Inferno", "{4}{R}", "6 damage", "removal"),
]
_TRICK_ORDER = {"deathtouch": 0, "pump": 1, "removal": 2, "flash": 3}


@lru_cache(maxsize=None)
def _texts():
    return load_card_text()


def land_colors(e):
    """Colours a land can make, e.g. 'UB'; '*' for any colour, '' if unknown."""
    name = e.get("card_name") or e.get("name") or ""
    if name in BASIC_COLOR:
        return BASIC_COLOR[name]
    c = _texts().get(name)
    if not c:
        return ""
    rules = " ".join(c.get("rules", []))
    if re.search(r"Add one mana of (any|the chosen) color", rules):
        return "*"
    found = "".join(re.findall(r"Add \{([WUBRGC])\}", rules))
    return "".join(x for x in "WUBRGC" if x in found)


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


class Body:
    """One creature for combat arithmetic."""
    def __init__(self, e):
        self.e = e
        self.i = e["i"]
        self.power = max(_int(e.get("power")) or 0, 0)
        self.toughness = _int(e.get("toughness")) or 0
        self.left = self.toughness - (e.get("damage") or 0)  # damage needed to kill it now
        kw = {k.lower() for k in e.get("keywords", [])}
        self.flying, self.reach, self.menace, self.trample = "flying" in kw, "reach" in kw, "menace" in kw, "trample" in kw
        self.vigilance, self.haste, self.deathtouch = "vigilance" in kw, "haste" in kw, "deathtouch" in kw
        self.indestructible = "indestructible" in kw
        self.double = "double strike" in kw
        self.first = "first strike" in kw or self.double

    def label(self):
        name = self.e.get("name") or (self.e.get("card_name") if not self.e.get("face_down") else None) or "face-down"
        hidden = " (face-down: keywords not shown)" if self.e.get("face_down") and not self.e["mine"] else ""
        return f"[{self.i}] {name} {self.power}/{self.toughness}{hidden}"

    def can_block(self, attacker):
        return not attacker.flying or self.flying or self.reach


_PUMP = re.compile(r"(?:target creature|enchanted creature|it)[^.]*?\bgets? \+(\d+)/\+(\d+)", re.I)
_GAINS = re.compile(r"\b(?:gains?|has) ((?:first strike|double strike|deathtouch|indestructible|trample|flying)"
                    r"(?:(?:,| and) (?:first strike|double strike|deathtouch|indestructible|trample|flying))*)", re.I)


def _mana_value(cost):
    return sum(int(x) if x.isdigit() else (0 if x.upper() == "X" else 1) for x in re.findall(r"\{([^}]+)\}", cost or ""))


def pump_tricks(entries):
    """Instant-speed pumps in this seat's own hand it can pay for with its untapped lands (colour not checked): an
    instant, or a card with flash, whose text gives a creature +X/+Y and/or combat keywords. [(entry, dp, dt,
    keywords, mana value)]; only the seat's own hand, which it sees."""
    lands = [e for e in entries[1:] if e["kind"] == "card" and e["zone"] == "BATTLEFIELD" and e["mine"]
             and "Land" in e.get("types", "") and not e.get("tapped")]
    out = []
    for e in entries[1:]:
        if e["kind"] != "card" or e["zone"] != "HAND" or not e["mine"]:
            continue
        c = _texts().get(e.get("name") or "")
        if not c:
            continue
        rules = " ".join(c.get("rules", []))
        types = c.get("types", "")
        if not ("Instant" in types or re.search(r"\bFlash\b", rules)):
            continue
        if "Creature" in types:
            continue  # a flash creature isn't a pump
        m = _PUMP.search(rules)
        kws = set()
        # a conditional upgrade (Violent Urge: "Delirium - If ..., that creature gains double strike") isn't counted
        plain = " ".join(x for x in re.split(r"(?<=\.)\s+", rules)
                         if "instead" not in x.lower() and not re.match(r"(Delirium|Eerie|Survival|If|As long as)\b", x))
        for g in _GAINS.findall(plain):
            kws |= {k.strip().lower() for k in re.split(r",| and ", g) if k.strip()}
        if not m and not kws:
            continue
        mv = _mana_value(c.get("cost"))
        if mv > len(lands):
            continue
        out.append((e, int(m.group(1)) if m else 0, int(m.group(2)) if m else 0, kws, mv))
    return sorted(out, key=lambda t: t[4])  # the cheapest first: lines show at most three


def opponent_tricks(entries, limit=6):
    """(untapped lands, their colours, tricks) for the opponent: OPP_TRICKS they could pay for with their untapped
    lands right now (one land per mana, each coloured pip needs a land of that colour). Public information only:
    the set's card pool, not their hand."""
    up = [e for e in entries[1:] if e["kind"] == "card" and e["zone"] == "BATTLEFIELD" and not e["mine"]
          and "Land" in e.get("types", "") and not e.get("tapped")]
    colors = [land_colors(e) for e in up]
    have = "".join(sorted({c for x in colors for c in x}, key="WUBRGC*".index))

    def payable(cost):
        pips = re.findall(r"\{([WUBRG])\}", cost)
        if _mana_value(cost) > len(up):
            return False
        free = list(colors)
        for p in sorted(pips, key=lambda p: sum(p in x or "*" in x for x in free)):  # scarcest colour first
            land = next((x for x in sorted(free, key=len) if p in x or "*" in x), None)
            if land is None:
                return False
            free.remove(land)
        return True

    ok = [t for t in OPP_TRICKS if payable(t[1])]
    ok.sort(key=lambda t: (_TRICK_ORDER[t[3]], _mana_value(t[1])))
    return len(up), have, ok[:limit]


def _opp_tricks_lines(entries, g, multi):
    if not g.get("opp_hand") or not _OPP_TRICKS_ON[0]:
        return []
    n, have, ok = opponent_tricks(entries)
    if not ok:
        return []
    out = [f"Opponent's possible tricks: {n} untapped land{'s' if n != 1 else ''}" + (f" ({have})" if have else "")
           + f", {_n(g['opp_hand'], 'card')} in hand. DSK instant-speed cards they could cast now (the set's pool, "
           "not their hand): " + "; ".join(f"{name} {cost} {what}" for name, cost, what, _ in ok) + "."]
    if multi and any(t[3] == "deathtouch" for t in ok):
        out.append("Against deathtouch/indestructible each extra blocker is an extra loss; extra blockers only help "
                   "against pumps.")
    return out


def boosted(body, dp, dt, kws):
    """A copy of a creature with a pump on it."""
    b = Body(body.e)
    b.power, b.toughness, b.left = b.power + dp, b.toughness + dt, b.left + dt
    b.first = b.first or "first strike" in kws or "double strike" in kws
    b.double = b.double or "double strike" in kws
    b.deathtouch = b.deathtouch or "deathtouch" in kws
    b.indestructible = b.indestructible or "indestructible" in kws
    b.trample = b.trample or "trample" in kws
    b.flying = b.flying or "flying" in kws
    return b


def _trick_name(t):
    e, dp, dt, kws, mv = t
    what = ", ".join(([f"+{dp}/+{dt}"] if dp or dt else []) + sorted(kws))
    return f"[{e['i']}] {e.get('name')} ({what}, mana value {mv})"


def creatures(entries, mine):
    return [Body(e) for e in entries[1:] if e["kind"] == "card" and e["zone"] == "BATTLEFIELD"
            and e["mine"] == mine and "Creature" in e.get("types", "")]


def _stunned(b):
    return bool((b.e.get("counters") or {}).get("stun"))


def fight(att, blockers):
    """Outcome of one attacker vs its blockers with no tricks. The attacker splits its damage to kill as many
    blockers as it can, cheapest first. Returns (attacker dies, list of blockers that die)."""
    hurt = {id(b): 0 for b in blockers}
    att_hurt = 0
    alive_b = list(blockers)
    att_alive = True
    for step in ("first", "regular"):
        deals_a = att_alive and (att.first if step == "first" else (not att.first or att.double))
        hitters = [b for b in alive_b if (b.first if step == "first" else (not b.first or b.double))]
        if deals_a:
            dmg = att.power
            for b in sorted(alive_b, key=lambda b: b.left - hurt[id(b)]):
                need = 1 if att.deathtouch else max(b.left - hurt[id(b)], 0)
                if dmg <= 0 or need > dmg:
                    break
                hurt[id(b)] += need
                dmg -= need
        att_hurt += sum(b.power for b in hitters)
        att_dies_now = not att.indestructible and (
            att_hurt >= att.left or (att_hurt > 0 and any(b.deathtouch for b in hitters)))
        dead_b = [b for b in alive_b if not b.indestructible and hurt[id(b)] > 0
                  and (hurt[id(b)] >= b.left or att.deathtouch)]
        alive_b = [b for b in alive_b if b not in dead_b]
        att_alive = att_alive and not att_dies_now
    return not att_alive, [b for b in blockers if b not in alive_b]


def min_through(attackers, blockers):
    """Least damage that gets through when every attacker attacks and the defender blocks to take as little as
    possible (chump blocks allowed). Blockers that fly or have reach can block anything; others not fliers."""
    air = sorted((b for b in blockers if b.flying or b.reach), key=lambda b: -b.toughness)
    ground = sorted((b for b in blockers if not (b.flying or b.reach)), key=lambda b: -b.toughness)
    atts = sorted(attackers, key=lambda a: -a.power)
    best_t = max([b.toughness for b in blockers] or [0])
    memo = {}

    def f(k, g, a):
        if k == len(atts):
            return 0
        key = (k, g, a)
        if key in memo:
            return memo[key]
        at = atts[k]
        blocked = max(at.power - (len(blockers) if at.deathtouch else best_t), 0) if at.trample else 0
        need = 2 if at.menace else 1
        res = at.power + f(k + 1, g, a)
        for ug in range(need + 1):  # ug ground blockers + (need - ug) air blockers
            ua = need - ug
            if (ug and at.flying) or ug > g or ua > a:
                continue
            res = min(res, blocked + f(k + 1, g - ug, a - ua))
        memo[key] = res
        return res

    return f(0, len(ground), len(air))


def _n(k, word):
    return f"{k} {word}" + ("" if k == 1 else "s")


def _fmt_list(bodies):
    return ", ".join(b.label() for b in bodies) or "none"


def _outcome(att, blockers):
    att_dies, dead = fight(att, blockers)
    parts = []
    parts.append("attacker dies" if att_dies else "attacker survives")
    if dead:
        parts.append(("blockers die: " if len(blockers) > 1 else "blocker dies") +
                     (", ".join(f"[{b.i}]" for b in dead) if len(blockers) > 1 else ""))
    else:
        parts.append("no blocker dies")
    if att.first and not any(b.first for b in blockers) and dead:
        parts.append("first strike: those deal no damage")
    return "; ".join(parts)


# the opponent's possible tricks are DSK's pool (OPP_TRICKS); other sets' games leave that line out (facts_block)
_OPP_TRICKS_ON = [True]


def facts(msg):
    """Lines for the 'Facts:' block of one decision, or [] when there's nothing worth saying."""
    entries = msg["obs"]["entries"]
    g = entries[0]
    if g.get("step") in (None, "null"):
        return []
    kind = msg["kind"]
    mine_c, opp_c = creatures(entries, True), creatures(entries, False)
    edges = msg["obs"].get("edges", [])
    blocks = [(a, b) for t, a, b in edges if t == "blocks"]  # blocker entry, attacker entry
    by_i = {b.i: b for b in mine_c + opp_c}
    out = []
    tricks = pump_tricks(entries)

    if g["my_turn"] and g["step"] in MAIN_STEPS and kind in ("PRIORITY", "ATTACK"):
        lands = [e for e in entries[1:] if e["kind"] == "card" and e["zone"] == "BATTLEFIELD" and e["mine"]
                 and "Land" in e.get("types", "")]
        up = [e for e in lands if not e.get("tapped")]
        cols = "".join(sorted({c for e in up for c in land_colors(e)}, key="WUBRGC*".index))
        out.append(f"Mana: {len(up)} untapped land{'s' if len(up) != 1 else ''}" + (f" ({cols})" if cols else "") +
                   ". Lands untap only in your next untap step: mana you spend this turn is not available on the "
                   "opponent's turn.")

        # who can block on the opponent's next turn, and what they can swing back for
        def home(b):
            return not b.e.get("tapped") and (not b.e.get("attacking") or b.vigilance)
        blockers_next = [b for b in mine_c if home(b)]
        away = [b for b in mine_c if not home(b)]
        opp_att = [b for b in opp_c if not (b.e.get("tapped") and _stunned(b))]  # all untap except stunned ones
        through = min_through(opp_att, blockers_next)
        line = (f"Opponent's next turn: your possible blockers {_fmt_list(blockers_next)}")
        if away:
            line += f"; not available (tapped or attacking, they stay tapped through that turn): {_fmt_list(away)}"
        line += (f". If all their creatures attack ({_n(len(opp_att), 'creature')}, {sum(b.power for b in opp_att)} power) and you "
                 f"block as well as possible, at least {through} gets through; you are at {g['my_life']}"
                 + (" (LETHAL)" if through >= g["my_life"] and through else "") + ".")
        out.append(line)

        # this turn's attack, as the board stands
        if g["step"] in ("Precombat Main", "Begin Combat", "Declare Attackers"):
            can_attack = [b for b in mine_c if b.e.get("attacking") or (
                not b.e.get("tapped") and (not b.e.get("summoning_sick") or b.haste))]
            opp_block = [b for b in opp_c if not b.e.get("tapped")]
            if can_attack:
                mt = min_through(can_attack, opp_block)
                out.append(f"Your attack this turn: {_n(len(can_attack), 'creature')} can attack "
                           f"({sum(b.power for b in can_attack)} power) into {len(opp_block)} untapped potential "
                           f"blockers; if all attack and they block to take as little as possible, at least {mt} "
                           f"gets through; opponent is at {g['opp_life']}" +
                           (" (LETHAL on board)" if mt >= g["opp_life"] else "") + ".")

    if kind == "ATTACK":
        opp_block = [b for b in opp_c if not b.e.get("tapped")]
        # one note per creature, though a creature that can also attack a planeswalker has two options
        cand = list({o["source"]["entry"]: by_i[o["source"]["entry"]] for o in msg["options"]
                     if "entry" in (o.get("source") or {}) and o["source"]["entry"] in by_i}.values())
        blockers_next = [b for b in mine_c if not b.e.get("tapped") and (not b.e.get("attacking") or b.vigilance)]
        opp_att = [b for b in opp_c if not (b.e.get("tapped") and _stunned(b))]
        for c in cand:
            alone = [b for b in opp_block if b.can_block(c)]
            if c.menace:
                note = "menace: needs two blockers"
            else:
                kills = [b for b in alone if fight(c, [b])[0]]
                free = [b for b in kills if not fight(c, [b])[1]]
                trades = [b for b in kills if b not in free]
                note = ("dies to a single block by " + ", ".join(f"[{b.i}]" for b in kills) +
                        (f" (trades with {', '.join(f'[{b.i}]' for b in trades)})" if trades else "") +
                        (f" (without killing it: {', '.join(f'[{b.i}]' for b in free)})" if free else "")
                        if kills else "no single untapped blocker kills it")
            pair = next(((x, y) for k, x in enumerate(alone) for y in alone[k + 1:] if fight(c, [x, y])[0]), None)
            if pair:
                note += f"; a double block like [{pair[0].i}]+[{pair[1].i}] kills it"
            if not c.vigilance:
                rest = [b for b in blockers_next if b.i != c.i]
                note += (f"; if it attacks it stays tapped through their next turn, and then at least "
                         f"{min_through(opp_att, rest)} gets through "
                         f"(you are at {g['my_life']})")
            out.append(f"Attack with {c.label()}: {note}.")
            for t in tricks[:3]:
                pumped = boosted(c, t[1], t[2], t[3])
                cells = [f"blocked by [{b.i}] {b.power}/{b.toughness} -> {_outcome(pumped, [b])}" for b in alone[:3]]
                if cells:
                    out.append(f"  ...if you cast {_trick_name(t)} on it after blocks ({pumped.power}/{pumped.toughness}): "
                               + " | ".join(cells) + ".")

    if kind == "ATTACK" and cand:
        out += _opp_tricks_lines(entries, g, multi=False)

    if kind == "BLOCK":
        attackers = [b for b in opp_c if b.e.get("attacking")]
        free = [b for b in mine_c if not b.e.get("tapped") and not b.e.get("blocking")]
        for a in attackers:
            mine_on = [by_i[x] for x, y in blocks if y == a.i and x in by_i]
            if mine_on:
                out.append(f"{a.label()} attacking, blocked by {_fmt_list(mine_on)}: {_outcome(a, mine_on)}.")
            ok = [b for b in free if b.can_block(a)]
            if a.menace and not mine_on:
                pairs = [(x, y) for k, x in enumerate(ok) for y in ok[k + 1:]]
                kill = next(((x, y) for x, y in pairs if fight(a, [x, y])[0]), None)
                if pairs:
                    out.append(f"{a.label()} attacking, menace (needs two blockers): " + (
                        f"e.g. [{kill[0].i}]+[{kill[1].i}] -> {_outcome(a, list(kill))}" if kill
                        else f"no pair of your blockers kills it; e.g. [{pairs[0][0].i}]+[{pairs[0][1].i}] -> "
                             f"{_outcome(a, list(pairs[0]))}"))
                continue
            cells = [f"[{b.i}] -> {_outcome(a, mine_on + [b])}" for b in ok]
            trick_lines = []
            for t in tricks[:3]:
                for b in ok[:3]:
                    pumped = boosted(b, t[1], t[2], t[3])
                    att_dies, dead = fight(a, [pumped])
                    trick_lines.append(f"if [{b.i}] blocks {a.label()} and you cast {_trick_name(t)} on it "
                               f"({pumped.power}/{pumped.toughness}): " + "; ".join(
                                   ["attacker dies" if att_dies else "attacker survives",
                                    "your blocker dies" if pumped in dead else "your blocker survives"]) + ".")
            if not mine_on:  # double blocks: show the ones that kill the attacker, the trap is the exact damage split
                cells += [f"[{x.i}]+[{y.i}] -> {_outcome(a, [x, y])}" for k, x in enumerate(ok) for y in ok[k + 1:]
                          if fight(a, [x, y])[0]][:3]
            if cells:
                out.append(f"{a.label()} attacking{', adding a blocker' if mine_on else ''}: " + " | ".join(cells))
            out += ["  ..." + x for x in trick_lines]
        unblocked = [a for a in attackers if not any(y == a.i for _, y in blocks)]
        if attackers:
            out.append(f"Unblocked so far: {sum(a.power for a in unblocked)} damage; you are at {g['my_life']}.")
            out += _opp_tricks_lines(entries, g, multi=len(free) + len(blocks) > 1)
    elif blocks and kind == "PRIORITY":
        for a in [b for b in mine_c + opp_c if b.e.get("attacking")]:
            on = [by_i[x] for x, y in blocks if y == a.i and x in by_i]
            if on:
                out.append(f"Combat now: {a.label()} blocked by {_fmt_list(on)}: {_outcome(a, on)}.")
                for t in tricks[:3]:
                    if a.e["mine"]:
                        pumped = boosted(a, t[1], t[2], t[3])
                        out.append(f"  ...if you cast {_trick_name(t)} on {a.label()} ({pumped.power}/{pumped.toughness}): "
                                   f"{_outcome(pumped, on)}.")
                    else:
                        for b in [x for x in on if x.e["mine"]][:2]:
                            pumped = boosted(b, t[1], t[2], t[3])
                            att_dies, dead = fight(a, [pumped if x is b else x for x in on])
                            out.append(f"  ...if you cast {_trick_name(t)} on your blocker [{b.i}] "
                                       f"({pumped.power}/{pumped.toughness}): "
                                       + ("attacker dies" if att_dies else "attacker survives") + "; "
                                       + ("your blocker dies" if pumped in dead else "your blocker survives") + ".")
    return out


def facts_block(msg, set_code="DSK"):
    """set_code: the seat's deck set; the opponent's-tricks line lists DSK cards, so it is only given in DSK games."""
    _OPP_TRICKS_ON[0] = set_code == "DSK"
    try:
        lines = facts(msg)
    finally:
        _OPP_TRICKS_ON[0] = True
    return ([f"Facts ({CAVEAT}):"] + ["- " + x for x in lines]) if lines else []
