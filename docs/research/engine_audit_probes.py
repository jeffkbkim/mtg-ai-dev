"""Expected-failing audit probes, not the project's regression suite.

Run explicitly with pytest and WITCHCRAFT_ROOT / HYPERDRAFT_ROOT pointing to
the pinned upstream checkouts in engine-comparison-2026-10-07.md. These small
boundary tests do not run complete games or validate the native Datalog engine.
"""

import os
import sys
from pathlib import Path

import pytest


@pytest.fixture
def witchcraft():
    root = Path(os.environ["WITCHCRAFT_ROOT"]).resolve()
    sys.path[:0] = [str(root / "packages"), str(root)]
    import mtg
    from mtg.engine import env, observe

    assert Path(mtg.__file__).is_relative_to(root), mtg.__file__
    return env, observe


def test_witchcraft_decision_seat_tracks_priority(witchcraft):
    env, _ = witchcraft
    state = {
        "is_player": {("alice",), ("bob",)},
        "active_player": {("alice",)},
        "current_step": {("precombat_main",)},
        "has_priority": {("bob",)},
    }
    assert env.to_move(state) == "bob"


def test_witchcraft_unknown_face_down_characteristics_are_indistinguishable(witchcraft):
    _, observe = witchcraft
    public = {
        "is_player": {("alice",), ("bob",)},
        "on_battlefield": {("opaque_id_1",)},
        "face_down": {("opaque_id_1",)},
        "known": {("alice", "opaque_id_1")},
        "printed_control": {("alice", "opaque_id_1")},
    }
    small = dict(public, printed_power={("opaque_id_1", 3)},
                 printed_toughness={("opaque_id_1", 4)})
    large = dict(public, printed_power={("opaque_id_1", 8)},
                 printed_toughness={("opaque_id_1", 8)})
    assert observe.observe(small, "bob") == observe.observe(large, "bob")


def test_witchcraft_six_unrestricted_attackers_offer_all_subsets(witchcraft, monkeypatch):
    env, _ = witchcraft
    # Isolate the action enumerator: the rules backend has already declared
    # these six attackers eligible, with no haste or must-attack constraints.
    answers = {"may_attack": {(f"c{i}",) for i in range(6)},
               "has_keyword": set(), "must_attack": set()}
    monkeypatch.setattr(env.driver, "run", lambda state, rels: {r: answers[r] for r in rels})
    options = env._attack_options({}, "alice")
    assert len(set(options)) == 64


def test_hyperdraft_using_impending_does_not_disable_second_copy():
    root = Path(os.environ["HYPERDRAFT_ROOT"]).resolve()
    sys.path.insert(0, str(root))
    from src.engine import Game, ZoneType
    from src.engine.impending import (
        is_impending_castable_from_hand, mark_impending_used, reset_impending_used,
    )
    from src.cards.duskmourn import OVERLORD_OF_THE_MISTMOORS as card_def

    reset_impending_used(card_def)
    try:
        game = Game()
        player = game.add_player("Alice")
        game.add_player("Bob")
        copies = [game.create_object(
            name=card_def.name, owner_id=player.id, zone=ZoneType.HAND,
            characteristics=card_def.characteristics, card_def=card_def,
        ) for _ in range(2)]
        assert all(is_impending_castable_from_hand(c, game.state, player.id) for c in copies)
        # This is the flag mutation used by the impending cast path; isolate
        # its eligibility consequence, without testing payment/resolution.
        mark_impending_used(copies[0].card_def)
        assert is_impending_castable_from_hand(copies[1], game.state, player.id)
    finally:
        reset_impending_used(card_def)
