"""ClaudePlayer's flip-only auto-pass (Jeff 2026-11-08): when the only option besides passing is turning a face-down
permanent up, Claude is asked only at the opponent's end step, in combat once attackers are declared, in its own
precombat main phase, and when an opponent spell or ability targets or could hurt its permanents."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "play"))
from players import ClaudePlayer  # noqa: E402

FLIP = "Special Action | face-down permanent | {2}{B}: Turn this face-down permanent face up."
player = object.__new__(ClaudePlayer)  # the rule reads only its message


def msg(stack=(), options=(FLIP,), edges=(), attacking=False, my_turn=False, step="Precombat Main"):
    g = {"i": 0, "turn": 9, "step": step, "my_turn": my_turn, "stack_size": len(stack)}
    es = [g, {"i": 1, "kind": "card", "zone": "BATTLEFIELD", "mine": True, "face_down": True, "attacking": attacking},
          {"i": 2, "kind": "card", "zone": "BATTLEFIELD", "mine": False}]
    es += [dict(s, i=10 + k, zone="STACK") for k, s in enumerate(stack)]
    return {"kind": "PRIORITY", "obs": {"entries": es, "edges": [list(e) for e in edges]},
            "options": [{"label": "PASS"}] + [{"label": x} for x in options]}, g


def skip(m):
    return player._flip_only_skip(*m)


COUNTERS = {"kind": "ability", "mine": False, "text": "When you unlock this door, put a +1/+1 counter on each of up to two target creatures."}
CREATURE = {"kind": "card", "mine": False, "name": "Hardened Escort"}


def test_skips_their_main_phases_spells_and_harmless_abilities():
    assert skip(msg([CREATURE]))                                 # Jeff's turn 22: Escort on the stack
    assert skip(msg([COUNTERS], edges=[("targets", 10, 2)]))     # their ability on their own creature
    assert skip(msg(step="Postcombat Main"))                     # their main phase, empty stack
    assert skip(msg(step="Combat Damage"))                       # after combat damage
    assert skip(msg(my_turn=True, step="Postcombat Main"))       # my second main: never flipped there
    assert skip(msg(my_turn=True, step="Upkeep"))


def test_asks_where_flips_happen():
    assert not skip(msg(step="End Turn"))                                   # their end step
    assert not skip(msg(step="Declare Blockers", attacking=True))           # combat with attackers
    assert not skip(msg(my_turn=True, step="Declare Attackers", attacking=True))
    assert not skip(msg(my_turn=True, step="Precombat Main"))               # my main phase


def test_asks_when_their_spell_or_ability_could_hurt_mine():
    assert not skip(msg([COUNTERS], edges=[("targets", 10, 1)]))            # targets my face-down creature
    assert not skip(msg([dict(COUNTERS, text="It deals 2 damage to each creature.")]))
    assert not skip(msg([{"kind": "card", "mine": False, "name": "Murder"}]))  # a spell, from its card text


def test_asks_when_something_else_can_be_played():
    assert not skip(msg(options=(FLIP, "Spell | Murder | Cast Murder")))
    assert not skip(msg(options=()))
