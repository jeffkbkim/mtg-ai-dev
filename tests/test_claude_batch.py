"""The Claude player's batched replies (play/batch.py, ClaudePlayer._from_batch): a plan answers the decisions it
names and nothing else; anything that differs drops it and the model is asked."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "play"))
import batch  # noqa: E402
from render import option_label  # noqa: E402


def entries(*cards, turn=5, step="Declare Attackers", my_turn=True, stack=0):
    g = {"i": 0, "turn": turn, "step": step, "my_turn": my_turn, "stack_size": stack, "my_life": 20, "opp_life": 20}
    return [g] + [dict(c, i=i + 1) for i, c in enumerate(cards)]


def card(name, mine=True, zone="BATTLEFIELD", **kw):
    return {"name": name, "mine": mine, "zone": zone, **kw}


def opt(label, src=None, tgt=None, action=None):
    o = {"label": label, "source": {"entry": src} if src is not None else {}, "target": tgt or {}}
    if action:
        o["action"] = action
    return o


def attack_msg(es, attackers):
    return {"kind": "ATTACK", "prompt": "declare attackers one at a time", "obs": {"entries": es},
            "options": [opt("DONE")] + [opt(f"{es[i]['name']} attacks", i, {"player": "opp"}) for i in attackers]}


def test_attack_plan_declares_the_rest_then_done():
    es = entries(card("Bear"), card("Wolf"), card("Glimmer"), card("Forest"))
    m = attack_msg(es, [1, 2, 3])
    plan = batch.make_plan(m, 1, {"attack": [1, 2]}, option_label)   # choice 1 = Bear attacks
    assert [s.get("done") or s["source"]["ref"] for s in plan["steps"]] == ["Wolf|mine", True]
    es2 = [dict(e) for e in es]
    es2[1]["attacking"] = True
    m2 = attack_msg(es2, [2, 3])
    k, _ = batch.next_choice(plan, m2, option_label)
    assert m2["options"][k]["label"] == "Wolf attacks"
    plan["pos"] += 1
    m3 = attack_msg(es2, [3])
    k, _ = batch.next_choice(plan, m3, option_label)
    assert m3["options"][k]["label"] == "DONE"


def test_attack_plan_drops_when_attacker_gone():
    es = entries(card("Bear"), card("Wolf"))
    plan = batch.make_plan(attack_msg(es, [1, 2]), 1, {"attack": [1, 2]}, option_label)
    try:
        batch.next_choice(plan, attack_msg(es, [1]), option_label)   # Wolf no longer offered
        assert False
    except LookupError:
        pass


def test_block_plan_matches_by_name_and_entry():
    es = entries(card("Bear"), card("Wolf"), card("Rat", mine=False, attacking=True), card("Rat", mine=False, attacking=True), step="Declare Blockers", my_turn=False)
    opts = [opt("DONE")] + [opt(f"{es[b]['name']} blocks Rat", b, {"entry": a}) for b in (1, 2) for a in (3, 4)]
    m = {"kind": "BLOCK", "prompt": "", "obs": {"entries": es}, "options": opts}
    plan = batch.make_plan(m, 1, {"blocks": [[1, 3], [2, 4]]}, option_label)   # choice: Bear blocks Rat [3]
    m2 = {**m, "options": [opt("DONE")] + [opt(f"Wolf blocks Rat", 2, {"entry": a}) for a in (3, 4)]}
    k, _ = batch.next_choice(plan, m2, option_label)
    assert m2["options"][k]["target"] == {"entry": 4}   # two Rats: the one still at the planned entry


def test_main_phase_chain_with_targets_and_pass():
    es = entries(card("Swamp", zone="HAND"), card("Murder", zone="HAND"), card("Wolf", mine=False), step="Precombat Main")
    m = {"kind": "PRIORITY", "prompt": "priority", "obs": {"entries": es},
         "options": [opt("PASS"), opt("Play land | Swamp | Play Swamp", 1)]}
    reply = {"choice": 1, "then": [{"do": "Cast Murder", "source": 2, "targets": [3]}, {"do": "PASS", "pass_until": "my_turn"}]}
    plan = batch.make_plan(m, 1, reply, option_label)
    assert [s["kind"] for s in plan["steps"]] == ["PRIORITY", "TARGET", "PRIORITY"]
    # the Swamp is on the battlefield now: entries shift
    es2 = entries(card("Swamp"), card("Murder", zone="HAND"), card("Wolf", mine=False), step="Precombat Main")
    m2 = {**m, "obs": {"entries": es2}, "options": [opt("PASS"), opt("Spell | Murder | Cast Murder", 2)]}
    k, _ = batch.next_choice(plan, m2, option_label)
    assert k == 1
    plan["pos"] += 1
    es3 = entries(card("Swamp"), card("Murder", zone="STACK"), card("Wolf", mine=False), step="Precombat Main", stack=1)
    m3 = {"kind": "TARGET", "prompt": "Select target creature", "obs": {"entries": es3},
          "options": [opt("Wolf", 2, {"entry": 3}, "TARGET")]}
    k, _ = batch.next_choice(plan, m3, option_label)
    assert k == 0
    plan["pos"] += 1
    m4 = {**m2, "options": [opt("PASS")]}
    k, step = batch.next_choice(plan, m4, option_label)
    assert k == 0 and step["pass_until"] == "my_turn"


def test_main_phase_chain_stops_on_opponent_stack_and_unplanned_target():
    es = entries(card("Swamp", zone="HAND"), card("Bear", zone="HAND"), card("Wolf", mine=False), step="Precombat Main")
    m = {"kind": "PRIORITY", "prompt": "priority", "obs": {"entries": es}, "options": [opt("PASS"), opt("Play land | Swamp | Play Swamp", 1)]}
    plan = batch.make_plan(m, 1, {"then": [{"do": "Cast Bear", "source": 2}]}, option_label)
    stacked = entries(card("Swamp"), card("Bear", zone="HAND"), card("Shock", mine=False, zone="STACK"), step="Precombat Main", stack=1)
    try:
        batch.next_choice(plan, {**m, "obs": {"entries": stacked}}, option_label)
        assert False
    except LookupError as e:
        assert "stack" in str(e)
    # a trigger's target the plan doesn't name is never answered
    plan2 = batch.make_plan(m, 1, {"then": [{"do": "Cast Bear", "source": 2}]}, option_label)
    plan2["pos"] = 1
    try:
        batch.next_choice(plan2, {"kind": "TARGET", "prompt": "", "obs": {"entries": es}, "options": [opt("Wolf", 2, {"entry": 3})]}, option_label)
        assert False
    except LookupError:
        pass


def test_bad_plan_is_rejected_not_guessed():
    es = entries(card("Bear"))
    try:
        batch.make_plan(attack_msg(es, [1]), 1, {"attack": [1, 7]}, option_label)
        assert False
    except ValueError:
        pass
    assert batch.make_plan(attack_msg(es, [1]), 0, {}, option_label) is None


def test_player_records_each_planned_decision(monkeypatch, tmp_path):
    import players
    p = players.ClaudePlayer.__new__(players.ClaudePlayer)
    p.batch, p.batch_dropped, p.pass_until, p.log, p.prompt_sha = None, None, None, [], "x"
    es = entries(card("Bear"), card("Wolf"))
    m = attack_msg(es, [1, 2])
    info = {}
    p._plan_batch(m, 1, {"choice": 1, "attack": [1, 2]}, "both swing", info)
    assert info["batch"]["pos"] == 0 and info["batch"]["of"] == 2
    es2 = [dict(e) for e in es]
    es2[1]["attacking"] = True
    k, i2 = p._from_batch(attack_msg(es2, [2]), es2[0])
    assert i2["auto"] == "batch" and i2["batch"]["pos"] == 1 and "(planned)" in i2["reason"]
    k, i3 = p._from_batch({**attack_msg(es2, []), "options": [opt("DONE")]}, es2[0])
    assert i3["batch"]["pos"] == 2 and p.batch is None
    # a plan that doesn't fit is dropped, and the next asked decision says why
    p._plan_batch(m, 1, {"attack": [1, 2]}, "both", {})
    assert p._from_batch({"kind": "PRIORITY", "prompt": "", "obs": {"entries": es}, "options": [opt("PASS")]}, es[0]) is None
    assert p.batch is None and "plan has ATTACK" in p.batch_dropped["why"]


def test_attack_plan_ending_without_done_is_not_a_fallback():
    import players
    p = players.ClaudePlayer.__new__(players.ClaudePlayer)
    p.batch, p.batch_dropped, p.pass_until, p.log, p.prompt_sha = None, None, None, [], "x"
    es = entries(card("Bear"), card("Wolf"))
    p._plan_batch(attack_msg(es, [1, 2]), 1, {"attack": [1, 2]}, "both", {})
    es2 = [dict(e) for e in es]
    es2[1]["attacking"] = True
    p._from_batch(attack_msg(es2, [2]), es2[0])     # Wolf declared from the plan; XMage then ends the attack itself
    assert p._from_batch({"kind": "PRIORITY", "prompt": "", "obs": {"entries": es2}, "options": [opt("PASS")]}, es2[0]) is None
    assert p.batch is None and p.batch_dropped is None
