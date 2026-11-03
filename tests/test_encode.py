import copy
import json
from pathlib import Path

import pytest
import torch

from engine.encode import (ACTION_TYPES, EDGE_TYPES, EMPTY_IDX, FACE_DOWN, PAD, Unmapped, Vocab, add_lands_played,
                           collate, encode_decision, encode_file)
from engine.batch_config import BatchConfig
from synthetic.fake_batch import validate_batch

FIXTURE = Path(__file__).parent / "fixtures" / "xmage_decisions_sample.jsonl"


@pytest.fixture(scope="module")
def vocab():
    return Vocab.load()


@pytest.fixture(scope="module")
def decisions():
    return [json.loads(line) for line in FIXTURE.read_text().splitlines()]


@pytest.fixture(scope="module")
def examples(vocab, decisions):
    return [encode_decision(d, vocab) for d in decisions]


def test_vocab_ids(vocab):
    assert PAD not in vocab.card_ids.values() and FACE_DOWN not in vocab.card_ids.values()
    assert len(set(vocab.card_ids.values())) == len(vocab.card_ids)
    assert len(set(vocab.ability_ids.values())) == len(vocab.ability_ids)
    assert min(vocab.ability_ids.values()) == 1
    assert "Plains" in vocab.card_ids and "Underwater Tunnel // Slimy Aquarium" in vocab.card_ids


def test_fixture_encodes_and_passes_validate_batch(vocab, examples):
    batch = collate(examples)
    validate_batch(batch, BatchConfig.from_vocab(vocab))
    assert batch["active_edges"].shape[1] == len(EDGE_TYPES)


def _placed(i, n, N):
    # compact entry index -> padded entry index (card j -> 1 + j, ability k -> 1 + N + k)
    if i <= 0:
        return i
    return i if i <= n else 1 + N + (i - 1 - n)


def test_action_indices_point_at_the_right_entries(vocab, decisions, examples):
    """An option's source/target must land on the entry the JSON pointed at, after padding."""
    batch = collate(examples)
    N = batch["card_ids"].shape[1]
    checked = 0
    for b, d in enumerate(decisions):
        entries = {e["i"]: e for e in d["obs"]["entries"]}
        cards = [e for e in d["obs"]["entries"][1:] if e["kind"] == "card"]
        for a, o in enumerate(d["options"]):
            for slot, field in (("source", "action_sources"), ("target", "action_targets")):
                ref = o.get(slot, {})
                got = batch[field][b, a].item()
                if "entry" not in ref:
                    assert got == EMPTY_IDX
                    continue
                e = entries[ref["entry"]]
                if e["kind"] == "global":
                    assert got == 0
                elif e["kind"] == "card":
                    assert 1 <= got <= len(cards)
                    assert cards[got - 1] is e
                else:
                    k = got - 1 - N
                    assert 0 <= k < len(examples[b].ability_ids)
                    assert batch["ability_ids"][b, k].item() == vocab.ability(e["ability_key"])
                checked += 1
    assert checked > 30


def test_player_targets_and_labels(decisions, examples):
    batch = collate(examples)
    for b, d in enumerate(decisions):
        assert batch["label"][b].item() == d["choice"]
        for a, o in enumerate(d["options"]):
            want = {"me": 1, "opp": 2}.get(o.get("target", {}).get("player"), 0)
            assert batch["action_target_players"][b, a].item() == want
            assert batch["action_types"][b, a].item() == ACTION_TYPES.index(o["action"])


def test_face_down_cards(vocab, decisions, examples):
    """Opponent face-down cards get the FACE_DOWN id; my own manifested card keeps its real identity."""
    seen_hidden = seen_mine = 0
    for d, x in zip(decisions, examples):
        cards = [e for e in d["obs"]["entries"][1:] if e["kind"] == "card"]
        for e, cid in zip(cards, x.card_ids):
            if not e.get("face_down"):
                continue
            if ": " in e["name"]:
                assert e["mine"]
                assert cid == vocab.card(e["name"].split(": ", 1)[1])
                seen_mine += 1
            else:
                assert cid == FACE_DOWN
                seen_hidden += 1
    assert seen_hidden > 0 and seen_mine > 0


def test_opponent_revealed_hand_card(vocab, decisions):
    """A card the opponent revealed from hand and still holds (zone HAND, mine false, revealed true) encodes as a
    known card in the HAND zone, not mine; the extra "revealed" field is ignored."""
    from engine.encode import CARD_FEATURES
    d = copy.deepcopy(decisions[0])
    entries = d["obs"]["entries"]
    entries.append({"kind": "card", "zone": "HAND", "name": "Glimmerburst", "card_name": "Glimmerburst", "mine": False,
                    "revealed": True, "face_down": False, "token": False, "types": "[INSTANT]", "mana_value": 2,
                    "power": "0", "toughness": "0", "i": len(entries)})
    x = encode_decision(d, vocab)
    n_cards = sum(e["kind"] == "card" for e in entries[1:])
    assert x.card_ids[n_cards - 1] == vocab.card("Glimmerburst")
    f = dict(zip(CARD_FEATURES, x.card_features[n_cards - 1]))
    assert f["zone_hand"] == 1.0 and f["mine"] == 0.0


def test_keywords_and_counters(vocab, decisions):
    """Two Reluctant Role Models, one with a flying counter and one with a lifelink counter, encode differently:
    each counter type has its own column and the keyword it grants shows in the has_ columns."""
    from engine.encode import CARD_FEATURES
    d = copy.deepcopy(decisions[0])
    entries = d["obs"]["entries"]
    base = {"kind": "card", "zone": "BATTLEFIELD", "name": "Reluctant Role Model", "card_name": "Reluctant Role Model",
            "mine": True, "face_down": False, "token": False, "types": "[Creature]", "mana_value": 2,
            "power": "2", "toughness": "2", "tapped": True, "damage": 0}
    entries.append({**base, "counters": {"flying": 1}, "keywords": ["flying"], "i": len(entries)})
    entries.append({**base, "counters": {"lifelink": 1, "stun": 2},
                    "keywords": ["lifelink", "ward&mdash;Discard a card.", "Equip {1}"], "i": len(entries)})
    x = encode_decision(d, vocab)
    n_cards = sum(e["kind"] == "card" for e in entries[1:])
    fly, life = (dict(zip(CARD_FEATURES, x.card_features[n_cards - k])) for k in (2, 1))
    assert fly["flying_counters/5"] == 0.2 and fly["has_flying"] == 1.0 and fly["has_lifelink"] == 0.0
    assert life["lifelink_counters/5"] == 0.2 and life["stun_counters/5"] == 0.4
    assert life["has_lifelink"] == 1.0 and life["has_ward"] == 1.0 and life["has_flying"] == 0.0

    entries[-1]["keywords"] = ["banding"]
    with pytest.raises(Unmapped, match="keyword"):
        encode_decision(d, vocab)
    entries[-1]["keywords"] = []
    entries[-1]["counters"] = {"oil": 1}
    with pytest.raises(Unmapped, match="counter"):
        encode_decision(d, vocab)


def _decision(turn, my_turn, action, seat):
    g = {"kind": "global", "turn": turn, "my_turn": my_turn}
    return {"seat": seat, "obs": {"entries": [g]}, "options": [{"action": "PASS"}, {"action": action}], "choice": 1}


def test_add_lands_played():
    """Old recordings: land drops are rebuilt from earlier PLAY_LAND choices in the same turn and game."""
    both = [_decision(1, True, "PLAY_LAND", "A"), _decision(1, False, "BLOCK", "B"), _decision(1, True, "CAST", "A"),
            _decision(2, True, "CAST", "B"), _decision(2, False, "PASS", "A"),
            _decision(1, True, "CAST", "A")]  # a second game in the same file
    add_lands_played(both)
    assert [d["obs"]["entries"][0]["lands_played"] for d in both] == [0, 1, 1, 0, 0, 0]

    one_seat = [_decision(1, True, "PLAY_LAND", "A"), _decision(2, False, "PASS", "A")]
    add_lands_played(one_seat)
    assert one_seat[0]["obs"]["entries"][0]["lands_played"] == 0
    assert "lands_played" not in one_seat[1]["obs"]["entries"][0]  # the opponent's turn: their land drops weren't recorded

    new = [_decision(3, True, "CAST", "A")]
    new[0]["obs"]["entries"][0]["lands_played"] = 1  # sent by the seat: kept as is
    add_lands_played(new)
    assert new[0]["obs"]["entries"][0]["lands_played"] == 1


def test_edges_follow_entries(decisions, examples):
    batch = collate(examples)
    N = batch["card_ids"].shape[1]
    total = 0
    for b, (d, x) in enumerate(zip(decisions, examples)):
        n = len(x.card_ids)
        remap = {0: 0}
        for j, e in enumerate(e for e in d["obs"]["entries"][1:] if e["kind"] == "card"):
            remap[e["i"]] = 1 + j
        for k, e in enumerate(e for e in d["obs"]["entries"][1:] if e["kind"] == "ability"):
            remap[e["i"]] = 1 + n + k
        for etype, f, t in d["obs"]["edges"]:
            assert batch["active_edges"][b, EDGE_TYPES.index(etype), _placed(remap[f], n, N), _placed(remap[t], n, N)]
            total += 1
        assert batch["active_edges"][b].sum().item() == len({tuple(e) for e in d["obs"]["edges"]})
    assert total > 0


def test_unknown_names_are_reported_not_replaced(vocab, decisions):
    d = copy.deepcopy(next(d for d in decisions if len(d["obs"]["entries"]) > 1))
    card = next(e for e in d["obs"]["entries"] if e["kind"] == "card" and not e.get("face_down"))
    card["name"] = card["card_name"] = "Not A Real Card"
    with pytest.raises(Unmapped):
        encode_decision(d, vocab)

    d = copy.deepcopy(decisions[0])
    d["options"][0]["source"] = {"unseen": True}
    with pytest.raises(Unmapped):
        encode_decision(d, vocab)


def test_encode_file_collects_problems(vocab, decisions, tmp_path):
    bad = copy.deepcopy(decisions[0])
    bad["obs"]["entries"][0]["step"] = "Not A Step"
    path = tmp_path / "games.jsonl"
    path.write_text("\n".join(json.dumps(d) for d in [decisions[0], bad, {"type": "end"}]))
    examples, problems = encode_file(path, vocab)
    assert len(examples) == 1
    assert problems == {"step not in list: 'Not A Step'": 1}


def test_modes_and_alt_costs_are_abilities(vocab, decisions, examples):
    """MODE options and the Impending cost carry an ability id; casting normally carries none; no named option."""
    batch = collate(examples)
    seen = 0
    for b, d in enumerate(decisions):
        entries = {e["i"]: e for e in d["obs"]["entries"] if "i" in e}
        for a, o in enumerate(d["options"]):
            ability = batch["action_abilities"][b, a].item()
            key = o.get("choice_key")
            if key and "#mode" in key:
                assert ability == vocab.ability(key)
                seen += 1
            elif key == "alt_cost:ImpendingAbility":
                card = entries[o["source"]["entry"]]["name"]
                assert ability == vocab.ability(f"{card}#alt:ImpendingAbility")
                seen += 1
            elif key == "alt_cost:none":
                assert ability == 0
            assert batch["action_named_options"][b, a].item() == 0  # nothing in the fixture is a named option
    assert seen >= 4  # 3 Silent Hallcreeper modes + Impending

    d = copy.deepcopy(next(d for d in decisions if d["kind"] == "CHOICE"))
    d["options"][0]["choice_key"] = "alt_cost:NotARealCost"
    with pytest.raises(Unmapped):
        encode_decision(d, vocab)
    del d["options"][0]["choice_key"]
    with pytest.raises(Unmapped):
        encode_decision(d, vocab)


def test_named_options(vocab, decisions):
    """Answers that are neither cards nor abilities (a colour) get a named option id; unknown ones are reported."""
    d = copy.deepcopy(next(d for d in decisions if d["kind"] == "CHOICE"))
    d["options"] = [dict(o, choice_key=k, source={}) for o, k in zip(d["options"], ["choice:White", "choice:Blue"])]
    d["choice"] = 0
    x = encode_decision(d, vocab)
    assert x.action_named_options == [vocab.named_option("choice:White"), vocab.named_option("choice:Blue")]
    assert x.action_abilities == [0, 0]
    d["options"][0]["choice_key"] = "choice:Purple"
    with pytest.raises(Unmapped):
        encode_decision(d, vocab)


def test_chosen_modes_on_the_stack(vocab, decisions):
    """A modal ability on the stack carries its chosen mode: from the seat's "modes", or from XMage's text."""
    d = copy.deepcopy(next(d for d in decisions if d["kind"] == "MODE"))
    stack = next(e for e in d["obs"]["entries"] if e.get("kind") == "ability" and e.get("ability_key") == "Silent Hallcreeper#0")
    want = vocab.ability("Silent Hallcreeper#mode2")

    stack["modes"] = ["Silent Hallcreeper#mode2"]
    x = encode_decision(d, vocab)
    assert want in [m for modes in x.ability_modes for m in modes]

    del stack["modes"]  # an older recording: only the rules text says which mode
    stack["text"] += " Chosen mode: {this} becomes a copy of another target creature you control."
    x = encode_decision(d, vocab)
    assert want in [m for modes in x.ability_modes for m in modes]
    batch = collate([x])
    assert batch["ability_modes"].shape[-1] == 1 and (batch["ability_modes"] == want).sum() == 1
    assert (batch["card_modes"] == 0).all()

    stack["modes"] = ["?"]
    with pytest.raises(Unmapped):
        encode_decision(d, vocab)


def test_keyword_rules_that_are_not_board_keywords_are_ignored():
    from engine.encode import _keyword
    assert _keyword("{this} can't be blocked.") == "can't be blocked"
    assert _keyword("Ward {2}") == "ward"
    assert _keyword("Swampcycling {2}") is None
    assert _keyword("If this card is in your opening hand, you may begin the game with it on the battlefield.") is None
