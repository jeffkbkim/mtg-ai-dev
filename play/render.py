"""Turn one seat's decision message (observation + options) into text a language model can read.

Only fields of the seat's own observation are used, so the text carries no more than the seat may know.
Card rules text comes from engine/vocab/dsk_card_text.json (public card text, as XMage implements it).
"""
import html, json, re
from pathlib import Path

CARD_TEXT_PATH = Path(__file__).resolve().parent.parent / "engine" / "vocab" / "dsk_card_text.json"


def clean(text):
    """XMage text can carry GUI markup and HTML entities (e.g. '<i>Eerie</i> &mdash;')."""
    text = html.unescape(re.sub(r"<[^>]+>", "", text or ""))
    # XMage's condition hints: "ICON_GOOD<text>" (condition met) / "ICON_BAD<text>" (not met)
    text = re.sub(r"ICON_GOOD(.*)$", r"[currently true: \1]", text)
    return re.sub(r"ICON_BAD(.*)$", r"[currently false: \1]", text)


def load_card_text(path=CARD_TEXT_PATH):
    return {c["name"]: c for c in json.loads(Path(path).read_text())}


def card_text(c):
    """One card's rules text, e.g. 'Gremlin Tamer {W}{U} [Creature] - [Human, Scout] 2/2: Eerie - ...'."""
    head = f"{c['name']} {c['cost']} {c['types']}" + (f" {c['pt']}" if "pt" in c else "")
    if "left" in c:
        doors = [f"door {h['name']} {h['cost']}: {' '.join(h['rules'])}" for h in (c["left"], c["right"])]
        return head + ". " + " | ".join(doors)
    return head + ": " + " ".join(c["rules"])


LOW_LIBRARY = 15


def _untapped_lands(entries, mine):
    lands = [e for e in entries if e["kind"] == "card" and e["zone"] == "BATTLEFIELD" and e["mine"] == mine
             and "Land" in e.get("types", "")]
    return f"untapped lands {sum(not e.get('tapped') for e in lands)} of {len(lands)}"


def _entry(e, entries=()):
    if e["kind"] == "global":
        # mulligans happen before the game: no step, and my_turn is false for both seats
        when = ("before the game (mulligan)" if e["step"] == "null" else
                f"turn {e['turn']}, {e['step']}, {'your' if e['my_turn'] else 'the opponent' + chr(39) + 's'} turn")
        warn = ""
        if e["my_library"] <= LOW_LIBRARY:
            warn += f" WARNING: only {e['my_library']} cards left in your library; drawing from an empty library loses the game."
        if e["opp_library"] <= LOW_LIBRARY:
            warn += f" The opponent has only {e['opp_library']} cards left in their library."
        return (f"{when}. Me: life {e['my_life']}, hand {e['my_hand']}, library {e['my_library']}, graveyard {e['my_graveyard']}, "
                f"{_untapped_lands(entries, True)}. "
                f"Opponent: life {e['opp_life']}, hand {e['opp_hand']}, library {e['opp_library']}, graveyard {e['opp_graveyard']}, "
                f"{_untapped_lands(entries, False)}. "
                f"Stack size {e['stack_size']}." + warn)
    if e["kind"] == "ability":
        return f"{'my' if e['mine'] else 'opp'} STACK ability of {e['source_name']}: {clean(e['text'])}"
    who = "my" if e["mine"] else "opp"
    # a Room with no unlocked door has an empty name but is face up
    name = e.get("name") or (e.get("card_name") if not e.get("face_down") else None) or "face-down card"
    if e.get("card_name") and e["card_name"] != name:
        name += f" (card: {e['card_name']})"
    # a card the opponent revealed from its hand and still holds: "opp HAND (revealed) <name>"
    zone = e["zone"] + (" (revealed)" if e.get("revealed") else "")
    parts = [f"{who} {zone} {name}"]
    if "types" in e:
        parts.append(e["types"].strip("[]"))
        if "Creature" in e["types"]:
            parts.append(f"{e['power']}/{e['toughness']}")
        if "Land" not in e["types"]:
            parts.append(f"mv {e['mana_value']}")
    flags = [f for f in ("face_down", "token", "tapped", "summoning_sick", "attacking", "blocking", "being_cast") if e.get(f)]
    if "Creature" not in e.get("types", ""):
        flags = [f for f in flags if f != "summoning_sick"]  # only matters for creatures
    if e.get("damage"):
        flags.append(f"damage {e['damage']}")
    if e.get("counters"):
        flags.append("counters " + ", ".join(f"{k} x{v}" for k, v in e["counters"].items()))
    if e.get("keywords"):
        flags.append("has " + ", ".join(clean(k) for k in e["keywords"]))
    if flags:
        parts.append("(" + ", ".join(flags) + ")")
    return " ".join(parts)


def _ref(r, entries):
    if not r:
        return None
    if "player" in r:
        return "me" if r["player"] == "me" else "opponent"
    if "entry" in r:
        e = entries[r["entry"]]
        return f"[{r['entry']}] " + (e.get("name") or e.get("source_name")
                                     or (e.get("card_name") if not e.get("face_down") else None) or "face-down card")
    return "unseen object"


BASICS = {"Plains", "Island", "Swamp", "Mountain", "Forest"}


def names_in(obs):
    """Card names visible in this observation (basic lands left out: their text is obvious)."""
    out = set()
    for e in obs["entries"]:
        for f in ("card_name", "name", "source_name"):
            if e.get(f):
                out.add(e[f])
    return out - BASICS


_TEXTS = None


def _door_label(label, src):
    """'Unlock the left half. (...)' -> 'Unlock door Slimy Aquarium: <its text>' using the Room's card text."""
    global _TEXTS
    m = re.search(r"Unlock the (left|right) half", label)
    if not m or not src or not src.get("card_name"):
        return label
    _TEXTS = _TEXTS or load_card_text()
    c = _TEXTS.get(src["card_name"])
    if not c or "left" not in c:
        return label
    door = c[m.group(1)]
    cost = label.split("|")[2].split(":")[0].strip() if label.count("|") >= 2 else door["cost"]
    return f"Unlock door {door['name']} for {cost} (sorcery speed): {' '.join(door['rules'])}"


def events(prev, cur):
    """What changed between two observations of the same seat, as short lines (only things this seat can see)."""
    if prev is None:
        return []
    out = []
    g0, g1 = prev["entries"][0], cur["entries"][0]
    for who in ("my", "opp"):
        if g0[f"{who}_life"] != g1[f"{who}_life"]:
            out.append(f"{'your' if who == 'my' else 'opponent'} life {g0[who + '_life']} -> {g1[who + '_life']}")
    def bag(obs):
        b = {}
        for e in obs["entries"][1:]:
            if e["kind"] != "card" or e["zone"] in ("OFFERED", "CASTING", "REVEALED") or e.get("revealed"):
                continue
            k = ("your" if e["mine"] else "opponent's", e["zone"].lower(), e.get("card_name") or e.get("name") or "face-down card")
            b[k] = b.get(k, 0) + 1
        return b
    b0, b1 = bag(prev), bag(cur)
    for k in sorted(set(b0) | set(b1)):
        d = b1.get(k, 0) - b0.get(k, 0)
        if d:
            who, zone, name = k
            out.append(f"{name} {'entered' if d > 0 else 'left'} {who} {zone}" + (f" (x{abs(d)})" if abs(d) > 1 else ""))
    # cards the opponent revealed from its hand (shown while they stay there), kept out of the bag above: they were
    # in that hand all along
    def revealed(obs):
        b = {}
        for e in obs["entries"][1:]:
            if e["kind"] == "card" and e.get("revealed") and e["zone"] == "HAND":
                n = e.get("card_name") or e.get("name") or "?"
                b[n] = b.get(n, 0) + 1
        return b
    r0, r1 = revealed(prev), revealed(cur)
    for name in sorted(set(r0) | set(r1)):
        d = r1.get(name, 0) - r0.get(name, 0)
        x = f" (x{abs(d)})" if abs(d) > 1 else ""
        if d > 0:
            out.append(f"opponent revealed {name} from hand" + x)
        elif d < 0:
            out.append(f"revealed {name} left the opponent's hand" + x)
    return out


def render(msg, new_cards=(), extra=()):
    """Text for one decision. new_cards: card text dicts to show (cards this seat sees for the first time).
    extra: lines placed after the state, before the decision (e.g. play/facts.py's block)."""
    entries = msg["obs"]["entries"]
    lines = ["State: " + _entry(entries[0], entries)]
    for e in entries[1:]:
        lines.append(f"[{e['i']}] {_entry(e)}")
    edge_words = {"blocks": "blocks", "attached_to": "is attached to", "targets": "targets", "resolves_before": "resolves before"}
    for t, a, b in msg["obs"].get("edges", []):
        if t in edge_words:
            lines.append(f"[{a}] {edge_words[t]} [{b}]")
    if new_cards:
        lines.append("Card text (first time you see these cards):")
        lines += ["  " + card_text(c) for c in new_cards]
    lines += list(extra)
    prompt = clean(msg["prompt"])
    lines.append(f"Decision: {msg['kind']}." + (f" {prompt}" if prompt.lower() != msg["kind"].lower() else ""))
    for k, o in enumerate(msg["options"]):
        extra = [x for x in (_ref(o.get("source"), entries), _ref(o.get("target"), entries)) if x]
        lines.append(f"{k}: {option_label(o, entries)}" + (f"   ({' -> '.join(extra)})" if extra else ""))
    return "\n".join(lines)


def option_label(o, entries):
    """An option's label as the player reads it (also used for the picked option in logs and transcripts)."""
    label = clean(o["label"])
    if "source" in o and "entry" in (o.get("source") or {}):
        label = _door_label(label, entries[o["source"]["entry"]])
    parts = label.split(" | ")
    if len(parts) == 3 and parts[0] in ("Spell", "Play land"):
        label = parts[2]  # "Spell | Glimmerburst | Cast Glimmerburst" -> "Cast Glimmerburst"
    if label == "?" and "player" in (o.get("target") or {}):
        label = "target " + _ref(o["target"], entries)  # a player target has no label of its own
    return label
