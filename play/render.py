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


def _entry(e):
    if e["kind"] == "global":
        step = e['step'] if e['step'] != 'null' else 'before the game'
        return (f"turn {e['turn']}, {step}, {'your' if e['my_turn'] else 'the opponent' + chr(39) + 's'} turn. "
                f"Me: life {e['my_life']}, hand {e['my_hand']}, library {e['my_library']}, graveyard {e['my_graveyard']}. "
                f"Opponent: life {e['opp_life']}, hand {e['opp_hand']}, library {e['opp_library']}, graveyard {e['opp_graveyard']}. "
                f"Stack size {e['stack_size']}."
                + (f" WARNING: only {e['my_library']} cards left in your library; drawing from an empty library loses the game."
                   if e["my_library"] <= 8 else ""))
    if e["kind"] == "ability":
        return f"{'my' if e['mine'] else 'opp'} STACK ability of {e['source_name']}: {clean(e['text'])}"
    who = "my" if e["mine"] else "opp"
    name = e.get("name") or "face-down card"
    if e.get("card_name") and e["card_name"] != name:
        name += f" (card: {e['card_name']})"
    parts = [f"{who} {e['zone']} {name}"]
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
        return f"[{r['entry']}] " + (e.get("name") or e.get("source_name") or "face-down card")
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
            if e["kind"] != "card" or e["zone"] in ("OFFERED", "CASTING", "REVEALED"):
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
    return out


def render(msg, new_cards=()):
    """Text for one decision. new_cards: card text dicts to show (cards this seat sees for the first time)."""
    entries = msg["obs"]["entries"]
    lines = ["State: " + _entry(entries[0])]
    for e in entries[1:]:
        lines.append(f"[{e['i']}] {_entry(e)}")
    edge_words = {"blocks": "blocks", "attached_to": "is attached to", "targets": "targets", "resolves_before": "resolves before"}
    for t, a, b in msg["obs"].get("edges", []):
        if t in edge_words:
            lines.append(f"[{a}] {edge_words[t]} [{b}]")
    if new_cards:
        lines.append("Card text (first time you see these cards):")
        lines += ["  " + card_text(c) for c in new_cards]
    lines.append(f"Decision: {msg['kind']}. {clean(msg['prompt'])}")
    for k, o in enumerate(msg["options"]):
        extra = [x for x in (_ref(o.get("source"), entries), _ref(o.get("target"), entries)) if x]
        label = clean(o["label"])
        if "source" in o and "entry" in (o.get("source") or {}):
            label = _door_label(label, entries[o["source"]["entry"]])
        if label == "?" and "player" in (o.get("target") or {}):
            label = "target " + _ref(o["target"], entries)
        lines.append(f"{k}: {label}" + (f"   ({' -> '.join(extra)})" if extra else ""))
    return "\n".join(lines)
