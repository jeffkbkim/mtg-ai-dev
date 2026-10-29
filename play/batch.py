"""Batched replies for the Claude player: one model answer that covers the decisions that follow it.

XMage asks one question at a time: each attacker, each blocker, each target, each spell of a main phase. The player
may answer the first with the whole plan (players.py RULES, "Batching"):

  ATTACK  "attack": [entry, ...]           every creature that attacks; the rest are declared, then DONE
  BLOCK   "blocks": [[blocker, attacker], ...]
  any     "targets": [entry | "opp" | "me", ...]   targets of the spell or ability just chosen, in the order asked
  PRIORITY in its own main phase with an empty stack:
          "then": [{"do": "<option text>", "source": entry, "targets": [...]}, ..., {"do": "PASS", "pass_until": ...}]

make_plan() turns that into steps naming cards (entry numbers shift as cards move), and next_choice() answers a later
decision from the next step, or says why it can't (the plan is then dropped and the model asked as usual): a decision
of another kind, a card or option that isn't there, two cards that can't be told apart, an opponent's object on the
stack, a new turn or step. Steps never answer a target the plan doesn't name: a trigger's target after the spell is
always asked.
"""
import itertools

_ids = itertools.count(1)


def ref(entry):
    """What a card is called across decisions: its name (or face-down) and whose it is."""
    if entry is None:
        return None
    name = "face-down" if entry.get("face_down") else entry.get("name") or "?"
    return f"{name}|{'mine' if entry.get('mine') else 'theirs'}"


def _entry(entries, i):
    return entries[i] if isinstance(i, int) and 0 < i < len(entries) else None


def _target_ref(entries, t):
    """A planned target: "opp"/"me" for a player, else the card at entry t. None if it doesn't exist."""
    if t in ("opp", "me"):
        return {"player": t}
    e = _entry(entries, t)
    return {"ref": ref(e), "i": t} if e else None


def _option_target(o, entries):
    t = o.get("target") or {}
    if "player" in t:
        return {"player": t["player"]}
    e = _entry(entries, t.get("entry"))
    return {"ref": ref(e), "i": t.get("entry")} if e else None


def _option_source(o, entries):
    e = _entry(entries, (o.get("source") or {}).get("entry"))
    return {"ref": ref(e), "i": (o.get("source") or {}).get("entry")} if e else None


def make_plan(msg, choice, reply, label_of):
    """Steps for the decisions after this one, from the reply's batch keys; [] when there are none.
    Raises ValueError for a plan that names an entry that isn't there (the plan is dropped, the choice stands)."""
    entries = msg["obs"]["entries"]
    g = entries[0]
    opt = msg["options"][choice]
    steps = []
    if msg["kind"] == "ATTACK" and isinstance(reply.get("attack"), list):
        chosen = _option_source(opt, entries)
        for a in reply["attack"]:
            e = _entry(entries, a)
            if e is None:
                raise ValueError(f"attack names entry {a}, which isn't there")
            if chosen and chosen["i"] == a:
                continue  # declared by this very choice
            steps.append({"kind": "ATTACK", "source": {"ref": ref(e), "i": a}})
        if opt["label"] != "DONE":
            steps.append({"kind": "ATTACK", "done": True})
    elif msg["kind"] == "BLOCK" and isinstance(reply.get("blocks"), list):
        cs, ct = _option_source(opt, entries), _option_target(opt, entries)
        for pair in reply["blocks"]:
            if not (isinstance(pair, list) and len(pair) == 2):
                raise ValueError(f"blocks has {pair!r}, not [blocker, attacker]")
            b, a = _entry(entries, pair[0]), _entry(entries, pair[1])
            if b is None or a is None:
                raise ValueError(f"blocks names {pair}, which aren't both there")
            if cs and ct and cs["i"] == pair[0] and ct.get("i") == pair[1]:
                continue
            steps.append({"kind": "BLOCK", "source": {"ref": ref(b), "i": pair[0]}, "target": {"ref": ref(a), "i": pair[1]}})
        if opt["label"] != "DONE":
            steps.append({"kind": "BLOCK", "done": True})
    else:
        for t in reply.get("targets") or []:
            tr = _target_ref(entries, t)
            if tr is None:
                raise ValueError(f"targets names {t}, which isn't there")
            steps.append({"kind": "TARGET", "target": tr})
        then = reply.get("then")
        if isinstance(then, list) and msg["kind"] == "PRIORITY" and g.get("my_turn") and g.get("step") in ("Precombat Main", "Postcombat Main") \
                and not g.get("stack_size"):
            for act in then:
                if not isinstance(act, dict) or not isinstance(act.get("do"), str):
                    raise ValueError(f"then has {act!r}, not {{\"do\": ...}}")
                if act["do"].strip().upper() == "PASS":
                    steps.append({"kind": "PRIORITY", "label": "PASS", "pass_until": act.get("pass_until")})
                    break  # nothing after a pass is this main phase's
                src = _entry(entries, act.get("source"))
                if act.get("source") is not None and src is None:
                    raise ValueError(f"then names source {act.get('source')}, which isn't there")
                steps.append({"kind": "PRIORITY", "label": act["do"].strip(), "source": {"ref": ref(src), "i": act["source"]} if src else None})
                for t in act.get("targets") or []:
                    tr = _target_ref(entries, t)
                    if tr is None:
                        raise ValueError(f"targets names {t}, which isn't there")
                    steps.append({"kind": "TARGET", "target": tr})
    if not steps:
        return None
    return {"id": next(_ids), "steps": steps, "pos": 0, "turn": g.get("turn"), "step": g.get("step"), "kind": msg["kind"]}


def _pick(cands, want_i, what):
    """One option from those matching by name: the only one, or the one still at the planned entry."""
    if len(cands) == 1:
        return cands[0][0]
    exact = [k for k, i in cands if i == want_i]
    if len(exact) == 1:
        return exact[0]
    raise LookupError(f"{what}: {len(cands)} options match and none is at the planned entry" if cands else f"{what}: no such option now")


def next_choice(plan, msg, label_of):
    """(option index, step) for this decision from the plan, or raises LookupError with why it doesn't fit."""
    if plan["pos"] >= len(plan["steps"]):
        raise LookupError("plan finished")
    step = plan["steps"][plan["pos"]]
    entries = msg["obs"]["entries"]
    g = entries[0]
    if msg["kind"] != step["kind"]:
        raise LookupError(f"asked {msg['kind']}, plan has {step['kind']}")
    if g.get("turn") != plan["turn"]:
        raise LookupError("a new turn")
    if step["kind"] in ("ATTACK", "BLOCK") and g.get("step") != plan["step"]:
        raise LookupError("combat moved on")
    if step["kind"] == "PRIORITY":
        if not (g.get("my_turn") and g.get("step") in ("Precombat Main", "Postcombat Main")):
            raise LookupError("not my main phase")
        if g.get("stack_size"):
            raise LookupError("something is on the stack")
    opts = msg["options"]
    if step.get("done"):
        k = next((k for k, o in enumerate(opts) if o["label"] == "DONE"), None)
        if k is None:
            raise LookupError("no DONE option")
        return k, step
    if step["kind"] == "ATTACK":
        cands = [(k, (_option_source(o, entries) or {}).get("i")) for k, o in enumerate(opts)
                 if o["label"] != "DONE" and (_option_source(o, entries) or {}).get("ref") == step["source"]["ref"]]
        return _pick(cands, step["source"]["i"], f"attacker {step['source']['ref']}"), step
    if step["kind"] == "BLOCK":
        cands = []
        for k, o in enumerate(opts):
            s, t = _option_source(o, entries), _option_target(o, entries)
            if s and t and s["ref"] == step["source"]["ref"] and t.get("ref") == step["target"]["ref"]:
                cands.append((k, (s["i"], t.get("i"))))
        return _pick(cands, (step["source"]["i"], step["target"]["i"]), f"block {step['source']['ref']} on {step['target']['ref']}"), step
    if step["kind"] == "TARGET":
        want = step["target"]
        if "player" in want:
            cands = [(k, None) for k, o in enumerate(opts) if (o.get("target") or {}).get("player") == want["player"]]
            return _pick(cands, None, f"target {want['player']}"), step
        cands = [(k, (_option_target(o, entries) or {}).get("i")) for k, o in enumerate(opts)
                 if o["label"] != "DONE" and (_option_target(o, entries) or {}).get("ref") == want["ref"]]
        return _pick(cands, want["i"], f"target {want['ref']}"), step
    # PRIORITY: the option with that text (and from that card, when the plan names one)
    cands = []
    for k, o in enumerate(opts):
        if label_of(o, entries).strip().lower() != step["label"].lower():
            continue
        s = _option_source(o, entries)
        if step.get("source") and (not s or s["ref"] != step["source"]["ref"]):
            continue
        cands.append((k, s["i"] if s else None))
    if step["label"] == "PASS":
        cands = cands[:1]
    # two copies of a card in hand are the same play
    if len(cands) > 1 and step.get("source") and len({opts[k]["label"] for k, _ in cands}) == 1:
        cands = cands[:1]
    return _pick(cands, (step.get("source") or {}).get("i"), f"\"{step['label']}\""), step
