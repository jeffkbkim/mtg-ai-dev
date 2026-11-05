"""ClaudePlayer passes priority on its own turn while only its own spells and abilities are on the stack, without
asking and without dropping the turn's planned plays; the opponent's turn, their spells and an empty stack are asked."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "play"))
import players  # noqa: E402
from test_claude_batch import entries, opt  # noqa: E402


def card(name, mine=True, zone="BATTLEFIELD", kind="card"):
    return {"name": name, "mine": mine, "zone": zone, "kind": kind}

only = players.ClaudePlayer._only_mine_on_stack


def prio(es, options=("Spell | Murder | Cast Murder",)):
    return {"kind": "PRIORITY", "prompt": "priority", "obs": {"entries": es, "edges": []},
            "options": [opt("PASS")] + [opt(x) for x in options]}


def test_passes_own_stack_on_my_turn_only():
    mine = entries(card("Bear", zone="STACK"), card("Bear trigger", zone="STACK", kind="ability"), step="Precombat Main", stack=2)
    assert only(prio(mine), mine[0])
    theirs = entries(card("Bear", zone="STACK"), card("Shock", mine=False, zone="STACK"), step="Precombat Main", stack=2)
    assert not only(prio(theirs), theirs[0])
    opp_turn = entries(card("Bear", zone="STACK"), step="Precombat Main", my_turn=False, stack=1)
    assert not only(prio(opp_turn), opp_turn[0])
    empty = entries(card("Bear"), step="Precombat Main")
    assert not only(prio(empty), empty[0])
    assert not only({**prio(mine), "kind": "TARGET"}, mine[0])


def test_plan_survives_my_own_spell_on_the_stack():
    p = players.ClaudePlayer.__new__(players.ClaudePlayer)
    p.batch, p.batch_dropped, p.pass_until, p.log, p.pending, p.prev_obs, p.prompt_sha = None, None, None, [], [], None, "x"
    es = entries(card("Swamp", zone="HAND"), card("Bear", zone="HAND"), step="Precombat Main")
    m = {"kind": "PRIORITY", "prompt": "priority", "obs": {"entries": es, "edges": []},
         "options": [opt("PASS"), opt("Play land | Swamp | Play Swamp", 1)]}
    p._plan_batch(m, 1, {"choice": 1, "then": [{"do": "Cast Bear", "source": 2}, {"do": "PASS", "pass_until": "my_turn"}]}, "go", {})
    es2 = entries(card("Swamp"), card("Bear", zone="HAND"), step="Precombat Main")
    k, info = p.choose({**m, "obs": {"entries": es2, "edges": []}, "options": [opt("PASS"), opt("Spell | Bear | Cast Bear", 2)]})
    assert k == 1 and info["auto"] == "batch"
    es3 = entries(card("Swamp"), card("Bear", zone="STACK"), step="Precombat Main", stack=1)
    k, info = p.choose(prio(es3, ()))
    assert k == 0 and info == {"auto": "own_stack"} and p.batch is not None
    es4 = entries(card("Swamp"), card("Bear"), step="Precombat Main")
    k, info = p.choose(prio(es4, ()))
    assert k == 0 and info["auto"] == "batch" and info["pass_until"] == "my_turn" and p.batch is None
