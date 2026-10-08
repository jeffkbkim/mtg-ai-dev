#!/usr/bin/env python3
"""Runnable reproduction of finding 1 in
docs/research/witchcraft-independent-verification-2026-10-07.md:
opponent instant responses are driver-greedy and bypass the seat policy.

Run:  pip install python-mtg==0.1.1   (Python 3.12)
      python experiments/response_probe.py

What it does (deterministic, seed=1):
  Phase A (no policies installed): Alice bolts on turn 1 while Bob has no
    mana (no response possible), both sides hold on Bob's turn 1, Alice bolts
    again on turn 2. Asserts Bob's Bolt fires in response.
  Phase B (recording spy policies on both seats): replays the identical line
    and asserts the identical outcome AND that no policy call concerning the
    response decision (whether to respond, which instant, target, mode)
    happens while the response resolves.

Expected outcome (asserted below):
  after Alice turn-1 Bolt: life {alice: 20, bob: 17}, Bob's graveyard empty
  after Alice turn-2 Bolt: life {alice: 17, bob: 14}, Bob's graveyard holds
    exactly 1 Bolt, Alice's holds 2, and the only policy calls recorded while
    the response resolved are the game's routine combat-phase checks
    ('attackers'/'blocks') -- nothing for the response decision itself.

Mana note: the driver's mana pool has no public observable on the Game API,
so the probe logs each side's battlefield lands before/after the response.
Bob's single Mountain is consistent with the single fired Bolt; the count
follows from available mana, which is orthogonal to the bypass being shown.
"""
import json
import re
import sys

from mtg import Game

SEED = 1
ALICE_DECK = ["Lightning Bolt"] * 4 + ["Mountain"] * 36
BOB_DECK = ["Lightning Bolt"] * 3 + ["Mountain"] * 37  # exactly 3: Bob can never draw a 4th
ALICE_HAND = ["Lightning Bolt"] * 2 + ["Mountain"] * 5
BOB_HAND = ["Lightning Bolt"] * 3 + ["Mountain"] * 4


def card_name(card_id):
    return re.sub(r"_\d+$", "", card_id)


def bolts(ids):
    return [c for c in ids if card_name(c) == "lightning_bolt"]


def find(g, kind, who=None):
    out = []
    for m in g.legal_moves:
        s = json.dumps(m, default=str)
        if f"'{kind}'" in s and (who is None or f"'{who}'" in s):
            out.append(m)
    return out


def make_spy(who, log):
    def spy(state, key, options, default):
        log.append((who, key))
        return default

    return spy


def play_line(policies):
    """Play the scripted line; return (game, response_window_calls).

    response_window_calls are the policy calls recorded while Alice's turn-2
    Bolt (and Bob's automatic response) resolved. Routine combat-phase checks
    ('attackers'/'blocks') may also fire as the turn continues inside the same
    push; those are unrelated to the response decision.
    """
    log = []
    pol = None
    if policies:
        pol = {seat: make_spy(seat, log) for seat in ("alice", "bob")}
    g = Game(
        decks={"alice": ALICE_DECK, "bob": BOB_DECK},
        seed=SEED,
        starting_hand={"alice": ALICE_HAND, "bob": BOB_HAND},
        policies=pol,
    )

    def alice_cast():
        ms = find(g, "cast", "alice")
        assert ms, "alice has no castable spell"
        g.push(ms[0].raw)

    def hold_until_alice_turn():
        for _ in range(80):
            if g.active_player == "alice":
                return
            ps = find(g, "pass")
            assert ps, "stuck: no pass move available"
            g.push(ps[0].raw)
        raise AssertionError("turn did not advance to alice")

    # Turn 1: Alice bolts. Bob has no lands yet, so no response is possible.
    alice_cast()
    assert g.life() == {"alice": 20, "bob": 17}, g.life()
    assert g.graveyard("bob") == [], g.graveyard("bob")
    print("t1: Alice bolts, Bob 20->17, no response (Bob has no mana)")

    # Bob's turn 1: hold everything (gets his land drop).
    hold_until_alice_turn()
    assert g.life() == {"alice": 20, "bob": 17}, g.life()
    print("bob t1: holds; battlefield lands:", g.battlefield())

    # Turn 2: Alice bolts again. Snapshot the spy log, then push through
    # the response window.
    calls_before = len(log)
    lands_before = dict(g.battlefield())
    alice_cast()
    new_calls = log[calls_before:]

    print("t2: Alice bolts again")
    print("  life:", g.life())
    print("  bob graveyard:", g.graveyard("bob"))
    print("  alice graveyard:", g.graveyard("alice"))
    print("  lands before/after:", lands_before, "->", dict(g.battlefield()))
    print("  policy calls during response window:", new_calls)
    return g, new_calls


def main():
    g, _ = play_line(policies=None)
    assert g.life() == {"alice": 17, "bob": 14}, g.life()
    assert len(bolts(g.graveyard("bob"))) == 1, g.graveyard("bob")
    assert len(bolts(g.graveyard("alice"))) == 2, g.graveyard("alice")
    print("phase A (no policies): Bob's Bolt fired in response -- OK")

    g, new_calls = play_line(policies=True)
    assert g.life() == {"alice": 17, "bob": 14}, g.life()
    assert len(bolts(g.graveyard("bob"))) == 1, g.graveyard("bob")
    assert len(bolts(g.graveyard("alice"))) == 2, g.graveyard("alice")
    # The response decision itself (whether to respond, which instant, its
    # target/mode) must never reach a seat policy. Only the game's routine
    # combat-phase checks may appear as the turn continues inside the push.
    assert all(k in ("attackers", "blocks") for _, k in new_calls), new_calls
    print("phase B (spy policies): identical outcome; no policy call for the")
    print("response decision itself (only routine attackers/blocks checks).")
    print("Bob's response never reached a seat policy.")
    print("ALL ASSERTIONS PASSED")


if __name__ == "__main__":
    sys.exit(main())
