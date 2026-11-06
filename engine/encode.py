"""Turn XMage seat observations (JSON lines from engine/xmage) into batches that follow the batch contract.

One decision line looks like {"kind", "prompt", "obs": {"entries", "edges"}, "options", "choice"}.
See /mnt/project-files/notes/xmage-step3-observation.md for the format.

Two steps:
    example = encode_decision(line, vocab)   # one decision -> small per-example tensors, entry order kept
    batch = collate([example, ...])          # pad and place entries as [global | cards (N) | abilities (N_a)]

Nothing unknown is silently replaced. A card name, token name, ability key, step or action type that isn't
in the vocabulary raises Unmapped; encode_file collects those into a report instead of dropping the game.

What an option means, three kinds:
- a pointer to an entry (action_sources / action_targets): a card, permanent or stack object
- an ability id (action_abilities): something that happens, including a mode ("Get Out#mode1") and an
  alternative cost ("Overlord of the Hauntwoods#alt:ImpendingAbility"); casting normally has no ability id
- a named option (action_named_options): an answer that is neither, like a colour or a counter type

Modal spells and abilities on the stack carry their chosen modes (card_modes / ability_modes, ability ids).
Recordings made before the seat sent "modes" only have them for abilities, read from XMage's "Chosen mode:"
text; a modal spell on the stack in those recordings has no modes.

Feature lists below are a first pass for the plumbing. Which features the model gets is a design choice:
change them freely, the layout comments say what each column is.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import torch
from torch import Tensor

VOCAB_DIR = Path(__file__).parent / "vocab"
VOCAB_PATH = VOCAB_DIR / "dsk_vocab.json"  # default; another set's file: vocab_path("FDN")


def vocab_path(set_code: str) -> Path:
    """engine/vocab/<set>_vocab.json, written by engine/xmage VocabDump with -Dmtg.set=<SET>."""
    return VOCAB_DIR / f"{set_code.lower()}_vocab.json"


PAD = 0
FACE_DOWN = 1  # card id for a card whose identity this seat may not know
EMPTY_IDX = -1

ZONES = ["HAND", "BATTLEFIELD", "GRAVEYARD", "EXILE", "STACK", "REVEALED", "OFFERED", "CASTING"]
CURRENT_TYPES = ["Creature", "Land", "Artifact", "Enchantment", "Instant", "Sorcery"]
STEPS = ["Untap", "Upkeep", "Draw", "Precombat Main", "Begin Combat", "Declare Attackers", "Declare Blockers",
         "First Combat Damage", "Combat Damage", "End Combat", "Postcombat Main", "End Turn", "Cleanup", "Pregame"]
PREGAME_STEPS = {None, "null"}  # XMage has no step before turn 1 (mulligans); the seat sends "null"
DECISION_KINDS = ["PRIORITY", "TARGET", "CHOOSE", "CHOOSE_CARDS", "TARGET_CARDS", "USE", "CHOICE", "MODE",
                  "TRIGGER_ORDER", "ATTACK", "BLOCK"]
# action type vocabulary; id = position, 0 = PAD
ACTION_TYPES = ["PAD", "PASS", "PLAY_LAND", "CAST", "ACTIVATE", "SPECIAL", "TARGET", "CHOOSE", "CHOOSE_CARDS",
                "TARGET_CARDS", "DONE", "ATTACK", "BLOCK", "YES", "NO", "MODE", "CHOICE", "TRIGGER_ORDER"]
EDGE_TYPES = ["blocks", "blocked_by", "attached_to", "has_attached", "targets", "targeted_by",
              "resolves_before", "resolves_after"]
TARGET_PLAYER = {"me": 1, "opp": 2}  # action_target_players: 0 = not a player
NAMED_CHOICE_ACTIONS = {"CHOICE", "MODE"}  # options whose meaning comes from their choice_key, not a card
NO_ALT_COST = "alt_cost:none"  # casting normally

# card feature layout (F columns)
# counter types seen in DSK games, (XMage name, column label); a count each, /5
COUNTER_TYPES = [("+1/+1", "plus1"), ("-1/-1", "minus1"), ("stun", "stun"), ("finality", "finality"),
                 ("time", "time"), ("rev", "rev"), ("possession", "possession"), ("nest", "nest"),
                 ("loyalty", "loyalty"), ("flying", "flying"), ("lifelink", "lifelink")]
# keywords a permanent has right now, from any source (printed, counter, Aura, until end of turn); 0/1 each.
# Cards off the battlefield get none: the seat only reports them for permanents (the card id covers printed text).
KEYWORDS = ["flying", "reach", "vigilance", "haste", "lifelink", "deathtouch", "menace", "trample", "first strike",
            "double strike", "hexproof", "indestructible", "defender", "ward", "can't be blocked",
            "can't attack or block alone"]
# keywords that are printed costs or casting permissions; the card id already says them and play doesn't change them
IGNORED_KEYWORDS = {"flash", "equip", "crew", "convoke", "ninjutsu"}  # plus any "<type>cycling"
CARD_FEATURES = (
    [f"zone_{z.lower()}" for z in ZONES]
    + ["mine", "face_down", "token", "tapped", "summoning_sick", "attacking", "blocking", "being_cast",
       "room_left_unlocked", "room_right_unlocked"]  # on the stack: which door is being cast
    + [f"is_{t.lower()}" for t in CURRENT_TYPES]
    + ["power/10", "toughness/10", "damage/10", "mana_value/10"]
    + [f"{label}_counters/5" for _, label in COUNTER_TYPES]
    + ["has_" + k.replace("'", "").replace(" ", "_") for k in KEYWORDS]
)
# ability-on-the-stack feature layout (F_a columns)
ABILITY_FEATURES = ["mine", "triggered", "activated"]
# global feature layout (K columns)
GLOBAL_FEATURES = (
    ["my_turn"] + [f"step_{s}" for s in STEPS] + [f"decision_{k.lower()}" for k in DECISION_KINDS]
    + ["my_life/20", "opp_life/20", "my_hand/7", "opp_hand/7", "my_library/40", "opp_library/40",
       "my_graveyard/20", "opp_graveyard/20", "stack_size/5", "turn/20", "lands_played"]
)  # turn: the game's turn number (both players' turns count); lands_played: by the active player this turn


class Unmapped(Exception):
    """Something in the observation has no vocabulary id. Never replaced; reported."""


@dataclass
class Vocab:
    card_ids: dict[str, int]
    ability_ids: dict[str, int]
    named_option_ids: dict[str, int]  # answers that are not cards or abilities, e.g. "choice:White"
    mode_texts: dict[str, list[tuple[str, str]]]  # card name -> [(mode key, mode text)], to read old recordings
    rooms: dict[str, tuple[str, str]]  # full Room name -> (left door, right door)
    door_to_room: dict[str, str]

    @classmethod
    def load(cls, path: Path = VOCAB_PATH) -> "Vocab":
        v = json.loads(Path(path).read_text())
        names = sorted(v["cards"]) + sorted(v.get("tokens", []))
        card_ids = {name: i + 2 for i, name in enumerate(names)}  # 0 PAD, 1 FACE_DOWN
        ability_ids = {a["key"]: i + 1 for i, a in enumerate(v["abilities"])}  # 0 = none / PAD
        named_option_ids = {c: i + 1 for i, c in enumerate(v.get("named_options", []))}  # 0 = not a named option
        mode_texts = {}
        for a in v["abilities"]:
            if a.get("type") == "Mode":
                mode_texts.setdefault(a["key"].rsplit("#", 1)[0], []).append((a["key"], a["text"]))
        rooms, door_to_room = {}, {}
        for name in v["cards"]:
            if " // " in name:
                left, right = name.split(" // ")
                rooms[name] = (left, right)
                door_to_room[left] = door_to_room[right] = name
        return cls(card_ids, ability_ids, named_option_ids, mode_texts, rooms, door_to_room)

    @property
    def num_cards(self) -> int:
        return max(self.card_ids.values()) + 1

    @property
    def num_abilities(self) -> int:
        return max(self.ability_ids.values()) + 1

    @property
    def num_named_options(self) -> int:
        return max(self.named_option_ids.values(), default=0) + 1

    def named_option(self, key: str) -> int:
        if key not in self.named_option_ids:
            raise Unmapped(f"named option not in vocabulary: {key!r}")
        return self.named_option_ids[key]

    def card(self, name: str) -> int:
        if name not in self.card_ids:
            raise Unmapped(f"card name not in vocabulary: {name!r}")
        return self.card_ids[name]

    def ability(self, key: str) -> int:
        if key not in self.ability_ids:
            raise Unmapped(f"ability key not in vocabulary: {key!r}")
        return self.ability_ids[key]


def _num(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _card_identity(e: dict, vocab: Vocab) -> tuple[int, bool, bool]:
    """Card id plus Room door flags. Face-down cards I may not know -> FACE_DOWN."""
    shown = e.get("name", "")
    if e.get("face_down"):
        # XMage shows "Manifest" to opponents and "Manifest: <real name>" to the controller
        if ": " in shown:
            return vocab.card(shown.split(": ", 1)[1]), False, False
        return FACE_DOWN, False, False
    full = e.get("card_name") or shown
    if full not in vocab.card_ids and shown in vocab.door_to_room:
        # one door of a Room cast as a spell shows only that door's name (no card_name);
        # the door flag then says which door is being cast
        full = vocab.door_to_room[shown]
    if full in vocab.rooms:
        left, right = vocab.rooms[full]
        if shown == left:
            return vocab.card(full), True, False
        if shown == right:
            return vocab.card(full), False, True
        if shown == full:
            return vocab.card(full), e.get("zone") == "BATTLEFIELD", e.get("zone") == "BATTLEFIELD"
        return vocab.card(full), False, False  # empty name: no door unlocked
    return vocab.card(full), False, False


def _card_features(e: dict, left: bool, right: bool) -> list[float]:
    zone = [1.0 if e.get("zone") == z else 0.0 for z in ZONES]
    flags = [float(bool(e.get(k))) for k in
             ("mine", "face_down", "token", "tapped", "summoning_sick", "attacking", "blocking", "being_cast")]
    flags += [float(left), float(right)]
    types = e.get("types") or ""
    current = [1.0 if t in types else 0.0 for t in CURRENT_TYPES]
    numbers = [_num(e.get("power")) / 10, _num(e.get("toughness")) / 10, _num(e.get("damage")) / 10,
               _num(e.get("mana_value")) / 10]
    counters = e.get("counters", {})
    unknown = set(counters) - {name for name, _ in COUNTER_TYPES}
    if unknown:
        raise Unmapped(f"counter type not in list: {sorted(unknown)}")
    counts = [counters.get(name, 0) / 5 for name, _ in COUNTER_TYPES]
    keywords = {_keyword(k) for k in e.get("keywords", [])}
    has = [1.0 if k in keywords else 0.0 for k in KEYWORDS]
    return zone + flags + current + numbers + counts + has


def _keyword(rule: str) -> str | None:
    """XMage keyword rule text -> an entry of KEYWORDS, or None for an ignored one.
    "ward {2}" and "ward&mdash;Discard a card." are both ward; "{this} can't be blocked." is can't be blocked."""
    s = rule.lower().removeprefix("{this} ").rstrip(".").strip()
    first = re.split(r" |&mdash;|—", s)[0]
    if first in IGNORED_KEYWORDS or first.endswith("cycling"):
        return None
    if s.startswith("if this card is in your opening hand"):  # Leyline of Resonance: only matters before turn 1
        return None
    for k in KEYWORDS:
        if s == k or s.startswith(k + " ") or s.startswith(k + "&mdash;") or s.startswith(k + "—"):
            return k
    raise Unmapped(f"keyword not in list: {rule!r}")


def _ability_features(e: dict) -> list[float]:
    t = str(e.get("ability_type", ""))
    return [float(bool(e.get("mine"))), float("Triggered" in t), float("Activated" in t)]


def _global_features(g: dict, kind: str) -> list[float]:
    step = "Pregame" if g.get("step") in PREGAME_STEPS else g["step"]
    if step not in STEPS:
        raise Unmapped(f"step not in list: {step!r}")
    if kind not in DECISION_KINDS:
        raise Unmapped(f"decision kind not in list: {kind!r}")
    return ([float(g["my_turn"])] + [1.0 if step == s else 0.0 for s in STEPS]
            + [1.0 if kind == k else 0.0 for k in DECISION_KINDS]
            + [g["my_life"] / 20, g["opp_life"] / 20, g["my_hand"] / 7, g["opp_hand"] / 7,
               g["my_library"] / 40, g["opp_library"] / 40, g["my_graveyard"] / 20, g["opp_graveyard"] / 20,
               g["stack_size"] / 5, g["turn"] / 20, float(_lands_played(g))])


def _lands_played(g: dict) -> int:
    if "lands_played" not in g:
        raise Unmapped("no lands_played in the global entry (recorded before the seat sent it; see add_lands_played)")
    return g["lands_played"]


def add_lands_played(decisions: list[dict]) -> None:
    """Fill the global entry's lands_played for recordings made before the seat sent it, in place.

    Rebuilt from the game's own decisions, in order: a land drop is a chosen PLAY_LAND option, and only the active
    player can make one. That needs every land drop to be in the list, so it only fills a decision when the seat
    whose turn it is was recorded (both seats of a Claude-vs-Claude game; only one seat's turns in a Playmat game).
    """
    recorded = {d.get("seat") for d in decisions}
    played: dict[int, int] = {}  # turn -> land drops so far
    last_turn = 0
    for d in decisions:
        g = d["obs"]["entries"][0]
        turn = g.get("turn") or 0
        if turn < last_turn:  # the next game in a file of several
            played = {}
        last_turn = turn
        if "lands_played" not in g and (len(recorded) == 2 or g.get("my_turn")):
            g["lands_played"] = played.get(turn, 0)
        choice = d.get("choice", -1)
        if 0 <= choice < len(d.get("options", [])) and d["options"][choice].get("action") == "PLAY_LAND":
            played[turn] = played.get(turn, 0) + 1


@dataclass
class Example:
    """One decision. Entry indices refer to `order`: 0 = global, then cards, then abilities (no padding yet)."""
    card_ids: list[int]
    card_features: list[list[float]]
    ability_ids: list[int]
    ability_features: list[list[float]]
    global_state: list[float]
    edges: list[tuple[int, int, int]]  # (edge type, from, to) in compact entry order
    action_types: list[int]
    action_sources: list[int]
    action_targets: list[int]
    action_abilities: list[int]
    action_target_players: list[int]
    action_named_options: list[int]
    label: int
    card_modes: list[list[int]] = field(default_factory=list)  # per card: chosen modes (ability ids), mostly []
    ability_modes: list[list[int]] = field(default_factory=list)  # per stack ability: chosen modes
    meta: dict = field(default_factory=dict)
    # every option that fits the record (17lands "ambiguous_set" rows); empty means just `label`
    label_set: list[int] = field(default_factory=list)
    weight: float = 1.0  # the decision's share of its turn's readings (turn_replay's world_share)
    won: float = -1.0  # did the deciding seat win the game: 1 or 0, -1 unknown (a cache built without --outcomes)


def encode_decision(d: dict, vocab: Vocab) -> Example:
    entries = d["obs"]["entries"]
    if entries[0]["kind"] != "global":
        raise ValueError("entry 0 must be the global entry")
    cards = [e for e in entries[1:] if e["kind"] == "card"]
    abilities = [e for e in entries[1:] if e["kind"] == "ability"]
    # dump index -> compact index [global | cards | abilities]
    remap = {0: 0}
    for j, e in enumerate(cards):
        remap[e["i"]] = 1 + j
    for k, e in enumerate(abilities):
        remap[e["i"]] = 1 + len(cards) + k

    card_ids, card_features, card_modes = [], [], []
    for e in cards:
        cid, left, right = _card_identity(e, vocab)
        card_ids.append(cid)
        card_features.append(_card_features(e, left, right))
        card_modes.append(_chosen_modes(e, vocab))
    ability_ids, ability_features, ability_modes = [], [], []
    for e in abilities:
        key = e.get("ability_key")
        if key is None:
            raise Unmapped(f"ability on the stack has no key: {e.get('source_name')!r}: {e.get('text', '')[:80]!r}")
        ability_ids.append(vocab.ability(key))
        ability_features.append(_ability_features(e))
        ability_modes.append(_chosen_modes(e, vocab))
    by_index = {e["i"]: e for e in entries if "i" in e}

    edges = []
    for etype, f, t in d["obs"].get("edges", []):
        if etype not in EDGE_TYPES:
            raise Unmapped(f"edge type not in list: {etype!r}")
        edges.append((EDGE_TYPES.index(etype), remap[f], remap[t]))

    types, sources, targets, abil, players, named = [], [], [], [], [], []
    for o in d["options"]:
        if o["action"] not in ACTION_TYPES:
            raise Unmapped(f"action type not in list: {o['action']!r}")
        types.append(ACTION_TYPES.index(o["action"]))
        src, tgt = o.get("source", {}), o.get("target", {})
        for ref in (src, tgt):
            if ref.get("unseen"):
                raise Unmapped(f"option refers to an object not in the observation ({d['kind']}: {o['label'][:60]!r})")
        sources.append(remap[src["entry"]] if "entry" in src else EMPTY_IDX)
        targets.append(remap[tgt["entry"]] if "entry" in tgt else EMPTY_IDX)
        players.append(TARGET_PLAYER.get(tgt.get("player"), 0))
        if o["action"] in NAMED_CHOICE_ACTIONS and not o.get("choice_key"):
            raise Unmapped(f"{o['action']} option has no choice key: {o['label'][:60]!r}")
        ability, option = _option_meaning(o, by_index.get(src.get("entry")), vocab)
        abil.append(ability)
        named.append(option)

    return Example(card_ids, card_features, ability_ids, ability_features,
                   _global_features(entries[0], d["kind"]), edges,
                   types, sources, targets, abil, players, named, d["choice"],
                   card_modes=card_modes, ability_modes=ability_modes, meta={"kind": d["kind"]})


def _option_meaning(o: dict, source: dict | None, vocab: Vocab) -> tuple[int, int]:
    """(ability id, named option id) of one option. The seat sends modes and alternative costs as choice keys."""
    key = o.get("choice_key")
    if not key:
        return (vocab.ability(o["ability_key"]) if o.get("ability_key") else PAD), 0
    if key == NO_ALT_COST:
        return PAD, 0
    if key.startswith("alt_cost:"):  # e.g. "alt_cost:ImpendingAbility" -> "<card being cast>#alt:ImpendingAbility"
        name = (source or {}).get("card_name") or (source or {}).get("name")
        if not name:
            raise Unmapped(f"alternative cost with no card to cast: {key!r}")
        return vocab.ability(f"{name}#alt:{key.split(':', 1)[1]}"), 0
    if "#mode" in key:
        return vocab.ability(key), 0
    return PAD, vocab.named_option(key)


def _chosen_modes(e: dict, vocab: Vocab) -> list[int]:
    """Ability ids of the modes chosen for a modal spell or ability on the stack; [] for everything else."""
    if "modes" in e:
        if "?" in e["modes"]:
            raise Unmapped(f"chosen mode the seat could not key: {e.get('name') or e.get('source_name')!r}")
        return [vocab.ability(k) for k in e["modes"]]
    text = e.get("text", "")
    if "Chosen mode" not in text:
        return []
    # older recordings: XMage appends "Chosen mode: <mode text>" to a modal ability's rules text
    card = e.get("ability_key", "#").rsplit("#", 1)[0]
    chosen = re.sub(r"<[^>]+>", " ", text.split("Chosen mode", 1)[1])
    found = [vocab.ability(k) for k, t in vocab.mode_texts.get(card, []) if t.rstrip(".").lower() in chosen.lower()]
    if not found:
        raise Unmapped(f"chosen mode not recognised: {card!r}: {chosen[:80]!r}")
    return found


def collate(examples: list[Example], label_sets: bool = False, outcomes: bool = False) -> dict[str, Tensor]:
    """Pad a list of examples into contract tensors. Card j -> entry 1 + j, ability k -> entry 1 + N + k."""
    B = len(examples)
    N = max(len(x.card_ids) for x in examples)
    N_a = max(len(x.ability_ids) for x in examples)
    A = max(len(x.action_types) for x in examples)
    K_m = max([1] + [len(m) for x in examples for m in x.card_modes + x.ability_modes])  # chosen modes per entry
    M = 1 + N + N_a
    F, F_a, K = len(CARD_FEATURES), len(ABILITY_FEATURES), len(GLOBAL_FEATURES)

    out = {
        "card_ids": torch.zeros(B, N, dtype=torch.long),
        "card_features": torch.zeros(B, N, F),
        "ability_ids": torch.zeros(B, N_a, dtype=torch.long),
        "ability_features": torch.zeros(B, N_a, F_a),
        "card_modes": torch.zeros(B, N, K_m, dtype=torch.long),
        "ability_modes": torch.zeros(B, N_a, K_m, dtype=torch.long),
        "global_state": torch.zeros(B, K),
        "active_edges": torch.zeros(B, len(EDGE_TYPES), M, M, dtype=torch.bool),
        "action_types": torch.zeros(B, A, dtype=torch.long),
        "action_sources": torch.full((B, A), EMPTY_IDX, dtype=torch.long),
        "action_targets": torch.full((B, A), EMPTY_IDX, dtype=torch.long),
        "action_abilities": torch.zeros(B, A, dtype=torch.long),
        "action_target_players": torch.zeros(B, A, dtype=torch.long),
        "action_named_options": torch.zeros(B, A, dtype=torch.long),
        "card_mask": torch.zeros(B, N, dtype=torch.bool),
        "ability_mask": torch.zeros(B, N_a, dtype=torch.bool),
        "action_mask": torch.zeros(B, A, dtype=torch.bool),
        "label": torch.zeros(B, dtype=torch.long),
    }
    for b, x in enumerate(examples):
        n, n_a, a = len(x.card_ids), len(x.ability_ids), len(x.action_types)

        def place(i: int) -> int:
            # compact index -> padded entry index
            if i <= 0:
                return i
            return i if i <= n else 1 + N + (i - 1 - n)

        out["card_ids"][b, :n] = torch.tensor(x.card_ids, dtype=torch.long)
        if n:
            out["card_features"][b, :n] = torch.as_tensor(x.card_features)  # a list, or a tensor from a cache
        out["card_mask"][b, :n] = True
        if n_a:
            out["ability_ids"][b, :n_a] = torch.tensor(x.ability_ids, dtype=torch.long)
            out["ability_features"][b, :n_a] = torch.tensor(x.ability_features)
        out["ability_mask"][b, :n_a] = True
        out["global_state"][b] = torch.tensor(x.global_state)
        for etype, f, t in x.edges:
            out["active_edges"][b, etype, place(f), place(t)] = True
        out["action_types"][b, :a] = torch.tensor(x.action_types, dtype=torch.long)
        out["action_sources"][b, :a] = torch.tensor([place(i) for i in x.action_sources], dtype=torch.long)
        out["action_targets"][b, :a] = torch.tensor([place(i) for i in x.action_targets], dtype=torch.long)
        out["action_abilities"][b, :a] = torch.tensor(x.action_abilities, dtype=torch.long)
        out["action_target_players"][b, :a] = torch.tensor(x.action_target_players, dtype=torch.long)
        out["action_named_options"][b, :a] = torch.tensor(x.action_named_options, dtype=torch.long)
        for j, modes in enumerate(x.card_modes):
            out["card_modes"][b, j, :len(modes)] = torch.tensor(modes, dtype=torch.long)
        for k, modes in enumerate(x.ability_modes):
            out["ability_modes"][b, k, :len(modes)] = torch.tensor(modes, dtype=torch.long)
        out["action_mask"][b, :a] = True
        out["label"][b] = x.label
    if label_sets:
        # opt-in (make_loaders turns it on for caches built with set labels): which options fit the record, and how
        # much each decision weighs. A plain one-hot `label` row has label_set = {label} and weight 1.
        out["label_set"] = torch.zeros(B, A, dtype=torch.bool)
        out["weight"] = torch.tensor([x.weight for x in examples])
        for b, x in enumerate(examples):
            out["label_set"][b, x.label_set or [x.label]] = True
    if outcomes:
        # opt-in (a cache built with --outcomes): the game's result for the deciding seat, the target of a value head
        out["won"] = torch.tensor([x.won for x in examples])
    return out


def encode_file(path: Path, vocab: Vocab) -> tuple[list[Example], dict[str, int]]:
    """Encode every decision in a JSON-lines file. Returns examples and a report of unmapped items (by message)."""
    decisions = [d for d in map(json.loads, Path(path).read_text().splitlines())
                 if d.get("type", "decision") == "decision"]
    return encode_decisions(decisions, vocab)


def encode_decisions(decisions: list[dict], vocab: Vocab,
                     keep: tuple[str, ...] = ()) -> tuple[list[Example], dict[str, int]]:
    """encode_file for decisions already read. keep: row fields copied into each example's meta (e.g. draft_id)."""
    examples, problems = [], {}
    add_lands_played(decisions)
    for d in decisions:
        if d.get("choice", 0) < 0:  # no label: an unmapped answer, or blocks the engine refused (Playmat records)
            key = f"no label: choice -1 ({d.get('mapping', '?')})"
            problems[key] = problems.get(key, 0) + 1
            continue
        try:
            x = encode_decision(d, vocab)
        except Unmapped as err:
            problems[str(err)] = problems.get(str(err), 0) + 1
            continue
        x.meta.update({k: d[k] for k in keep if k in d})
        examples.append(x)
    return examples, problems
