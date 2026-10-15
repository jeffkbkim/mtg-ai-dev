import copy
import json
from pathlib import Path

import pytest
import torch

from engine.encode import (ACTION_TYPES, EDGE_TYPES, EMPTY_IDX, FACE_DOWN, PAD, Unmapped, Vocab, collate,
                           encode_decision, encode_file)
from synthetic.fake_batch import FakeBatchConfig, validate_batch

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
    cfg = FakeBatchConfig(vocab_card=vocab.num_cards, vocab_ability=vocab.num_abilities, vocab_action=len(ACTION_TYPES))
    validate_batch(batch, cfg)
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


def test_named_choices(vocab, decisions, examples):
    """CHOICE / MODE options carry a named choice id (meaning, not list position); other options carry 0."""
    batch = collate(examples)
    seen = 0
    for b, d in enumerate(decisions):
        for a, o in enumerate(d["options"]):
            got = batch["action_choices"][b, a].item()
            if o["action"] in ("CHOICE", "MODE"):
                assert got == vocab.choice(o["choice_key"])
                seen += 1
            else:
                assert got == 0
    assert seen > 0
    assert "alt_cost:ImpendingAbility" in vocab.choice_ids and "alt_cost:none" in vocab.choice_ids

    d = copy.deepcopy(next(d for d in decisions if d["kind"] == "CHOICE"))
    d["options"][0]["choice_key"] = "alt_cost:NotARealCost"
    with pytest.raises(Unmapped):
        encode_decision(d, vocab)
    del d["options"][0]["choice_key"]
    with pytest.raises(Unmapped):
        encode_decision(d, vocab)
