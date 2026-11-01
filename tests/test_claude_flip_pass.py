"""ClaudePlayer's flip-only auto-pass: an opponent's ability on the stack, when the only other option is turning a
face-down permanent up, is passed without asking; spells, combat, an empty stack and abilities aimed at Claude's
permanents are still asked."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "play"))
from players import ClaudePlayer  # noqa: E402

FLIP = "Special Action | face-down permanent | {2}{B}: Turn this face-down permanent face up."
player = object.__new__(ClaudePlayer)  # the rule reads only its message


def msg(stack, options=(FLIP,), edges=(), attacking=False, turn=False):
    g = {"i": 0, "turn": 9, "step": "Precombat Main", "my_turn": turn, "stack_size": len(stack)}
    es = [g, {"i": 1, "kind": "card", "zone": "BATTLEFIELD", "mine": True, "face_down": True, "attacking": attacking},
          {"i": 2, "kind": "card", "zone": "BATTLEFIELD", "mine": False}]
    es += [dict(s, i=10 + k, zone="STACK") for k, s in enumerate(stack)]
    return {"kind": "PRIORITY", "obs": {"entries": es, "edges": [list(e) for e in edges]},
            "options": [{"label": "PASS"}] + [{"label": x} for x in options]}


COUNTERS = {"kind": "ability", "mine": False, "ability_type": "Triggered",
            "text": "When you unlock this door, put a +1/+1 counter on each of up to two target creatures."}


def test_passes_their_harmless_ability_when_only_flips():
    assert player._flip_only_on_their_ability(msg([COUNTERS], edges=[("targets", 10, 2)]))


def test_asks_for_spells_empty_stack_and_combat():
    assert not player._flip_only_on_their_ability(msg([{"kind": "card", "mine": False, "name": "Cryptid Inspector"}]))
    assert not player._flip_only_on_their_ability(msg([]))
    assert not player._flip_only_on_their_ability(msg([COUNTERS], attacking=True))


def test_asks_when_aimed_at_my_permanent_or_harmful():
    assert not player._flip_only_on_their_ability(msg([COUNTERS], edges=[("targets", 10, 1)]))
    hurt = dict(COUNTERS, text="When this enters, it deals 2 damage to any target.")
    assert not player._flip_only_on_their_ability(msg([hurt]))


def test_asks_when_something_else_can_be_played():
    assert not player._flip_only_on_their_ability(msg([COUNTERS], options=(FLIP, "Spell | Murder | Cast Murder")))
    assert not player._flip_only_on_their_ability(msg([dict(COUNTERS, mine=True)]))
