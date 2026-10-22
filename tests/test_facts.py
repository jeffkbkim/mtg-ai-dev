"""play/facts.py on small hand-built boards, one per kind of slip the game reviewer flagged."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "play"))
from facts import Body, facts, fight, min_through  # noqa: E402


def card(i, mine, p, t, **kw):
    keywords = kw.pop("keywords", [])
    e = {"kind": "card", "zone": "BATTLEFIELD", "i": i, "mine": mine, "name": f"c{i}", "types": "[Creature]",
         "power": str(p), "toughness": str(t), "tapped": False, "damage": 0, "summoning_sick": False,
         "attacking": False, "blocking": False, "face_down": False, **kw}
    if keywords:
        e["keywords"] = keywords
    return e


def land(i, mine, name, tapped=False):
    return {"kind": "card", "zone": "BATTLEFIELD", "i": i, "mine": mine, "name": name, "card_name": name,
            "types": "[Land]", "tapped": tapped}


def glob(step="Precombat Main", my_turn=True, my_life=20, opp_life=20):
    return {"kind": "global", "i": 0, "turn": 5, "step": step, "my_turn": my_turn, "my_life": my_life,
            "opp_life": opp_life, "stack_size": 0}


def b(**kw):
    return Body(card(kw.pop("i", 1), kw.pop("mine", True), kw.pop("p"), kw.pop("t"), **kw))


def test_first_strike_kills_blocker_before_it_deals_damage():
    # part15 game0: a 1/3 blocked a 3-power first striker "to survive"
    att_dies, dead = fight(b(p=3, t=4, keywords=["first strike"]), [b(i=2, p=1, t=3)])
    assert not att_dies and len(dead) == 1


def test_double_block_damage_splits_exactly():
    # batch01 part20 game1: 3/1 + 4/3 double-blocking a 4/5; 4 damage kills both
    loner, skin = b(i=2, p=3, t=1), b(i=3, p=4, t=3)
    att_dies, dead = fight(b(p=4, t=5), [loner, skin])
    assert att_dies and dead == [loner, skin]


def test_deathtouch_and_indestructible():
    att_dies, dead = fight(b(p=1, t=1, keywords=["deathtouch"]), [b(i=2, p=5, t=5)])
    assert att_dies and len(dead) == 1
    att_dies, dead = fight(b(p=4, t=3, keywords=["indestructible"]), [b(i=2, p=5, t=5)])
    assert not att_dies and not dead


def test_min_through_respects_flying_and_menace():
    flier, menace, ground = b(i=1, p=3, t=3, keywords=["flying"]), b(i=2, p=4, t=4, keywords=["menace"]), b(i=3, p=2, t=2)
    one_ground = [b(i=9, p=1, t=1)]
    # one ground blocker can't block the flier and can't block menace alone: it chumps the 2/2
    assert min_through([flier, menace, ground], one_ground) == 7
    assert min_through([flier, menace, ground], one_ground + [b(i=8, p=1, t=1, keywords=["reach"])]) == 4


def test_attackers_stay_tapped_and_crack_back():
    # batch02 part13 game0: "my creatures untap before their turn"; the attack line says otherwise and counts
    # the swing back without that creature
    entries = [glob(my_life=5), card(1, True, 3, 3), card(2, False, 3, 3), card(3, False, 3, 3), land(4, True, "Forest")]
    msg = {"kind": "ATTACK", "obs": {"entries": entries, "edges": []},
           "options": [{"label": "DONE"}, {"label": "c1 attacks", "source": {"entry": 1}}]}
    lines = facts(msg)
    assert any(l.startswith("Mana: 1 untapped land (G)") for l in lines)
    nxt = next(l for l in lines if l.startswith("Opponent's next turn"))
    assert "at least 3 gets through" in nxt
    att = next(l for l in lines if l.startswith("Attack with [1]"))
    assert "stays tapped through their next turn" in att and "at least 6 gets through" in att


def test_block_lines_show_double_blocks_that_kill_both():
    attacker = card(5, False, 4, 5, attacking=True, tapped=True)
    entries = [glob(step="Declare Blockers", my_turn=False), attacker, card(6, True, 3, 1), card(7, True, 4, 3)]
    msg = {"kind": "BLOCK", "obs": {"entries": entries, "edges": []}, "options": [{"label": "DONE"}]}
    line = next(l for l in facts(msg) if l.startswith("[5]"))
    assert "[6]+[7] -> attacker dies; blockers die: [6], [7]" in line


def test_no_facts_before_the_game():
    msg = {"kind": "USE", "obs": {"entries": [glob(step="null")], "edges": []}, "options": []}
    assert facts(msg) == []
