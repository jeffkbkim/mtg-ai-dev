# Independent verification of Witchcraft boundary probes — 2026-10-07

This report independently re-verifies the four Witchcraft boundary findings from
[DSK engine feasibility tests](../../experiments/engine_smoke/README.md) and
[engine comparison](engine-comparison-2026-10-07.md), because they gate the
engine decision. Every load-bearing claim below was checked against the primary
source (installed package source, executed locally) rather than relayed from
another agent's screenshots. Verification level is labeled per finding:
**dynamic** (executed a probe and observed behavior) or **static** (read the
code path; unambiguous, but not executed end-to-end).

## Environment

- `python-mtg==0.1.1` installed from PyPI into a fresh venv (Python 3.12).
- Upstream source cloned for reference: `yevbar/witchcraft` at `e35821c`
  ("Fix remaining combat, continuous-effect and card coverage failures") —
  the same commit inspected in the earlier audit.
- Line numbers below refer to the installed package
  (`site-packages/mtg/...`) unless noted as the source repo.

## 1. Opponent instant responses are driver-greedy — CONFIRMED (dynamic + static)

**Mechanism.** Casting (or activating) through `Game.push` reaches
`env.step`, which calls `driver._resolve_stack(s, ap, players)`
(`mtg/engine/env.py:567`). `_resolve_stack` (`mtg/driver.py:3721`) opens a
response window for each non-active player via `_cast_instant_response`
(`mtg/driver.py:3700`). That function is greedy by construction: it collects
the player's castable instants, sorts them, casts the first one, then re-opens
priority and repeats until none remain. The whether-to-respond and
which-instant decisions never pass through the `_choose` referee seam, so an
installed seat policy is never consulted for them.

**Dynamic probe.** Fixed starting hands (seed=1): Alice and Bob each hold
Lightning Bolt + 6 Mountain. Alice bolts on turn 1 (Bob has no mana: no
response possible, Bob 20→17). Both sides hold on Bob's turn 1. Alice bolts
again on turn 2 with Bob holding 3 Bolts and an untapped Mountain. The driver
fired all three of Bob's Bolts in response without any policy input: Alice
20→11, Bob 17→14, Bob's graveyard gained 3 Bolts. No player object was
installed, but the code path proves none could have been consulted — there is
no `_choose` call on that path.

**Nuance not in the earlier report.** The response's *mode* (`_choose_mode`
routes through `_choose`) and *target* (target selection routes through
`_choose` with a greedy default) are policy-overridable when a policy is
installed. The bypass is specifically the two highest-leverage decisions:
whether to respond at all, and with which spell.

**Corroborating note.** The `instant_speed` flag docstring in `mtg/game.py`
states: "Reactive windows on the OPPONENT's turn need priority passing, not
yet modeled." The greedy auto-responder is currently the only response
mechanism.

## 2. Combat enumeration capped at 5 attackers — CONFIRMED (static; arithmetic matches the dynamic 8-vs-64)

`_MAX_SUBSET_ATOMS = 5` (`mtg/engine/env.py:38`). `_attack_options`
(`mtg/engine/env.py:183`) enumerates every attacker subset up to that many
eligible attackers; above it, it offers only: attack with all, each singleton
attacker, and attack with none (when no forced attackers). Six eligible
attackers therefore yield 1 + 6 + 1 = **8** options instead of 2^6 = **64** —
the arithmetic exactly reproduces the earlier dynamic measurement.

This is a deliberate branching-factor cap ("policy cap"), not an accidental
bug. For training it still means the action space is incomplete by design
above five attackers: the agent can never learn a subset attack the enumerator
did not offer.

*Honesty note: I did not run a dynamic six-attacker game. The code is five
unambiguous lines, and its arithmetic exactly reproduces the earlier
independent dynamic measurement.*

## 3. Face-down observation leaks printed power/toughness — CONFIRMED (static)

`observe()` (`mtg/engine/observe.py`) redacts face-down cards' identity via
`_IDENTITY_RELS` (`mtg/engine/observe.py:34`):

```python
_IDENTITY_RELS = frozenset({"instance_of", "printed_subtype", "printed_color", "mana_cost", "spell_type"})
```

`printed_power` and `printed_toughness` are real state relations (populated in
`mtg/driver.py:880`) but are **not** in the scrub set, so a face-down card's
printed stats survive redaction. A policy reading observations can effectively
see morphs' and manifested cards' stats. The fix is small (add the two
relations to the set); the finding is that no test covered it.

## 4. Rooms: later paid unlocking unmodeled — CONFIRMED (static)

`packages/mtg/bridge_to_engine.py:252` (source repo) maps "when you unlock
this door" to the enter-the-battlefield event of the door that was cast. There
is no path for paying to unlock the second door later in the game. This
matches the earlier audit's observation that Rooms can report no bridge
omissions despite missing behavior.

## Verdict on the earlier claims

All four findings confirmed. Two nuances added: (a) response mode/target
sub-choices *are* policy-steerable via `_choose` — the bypass is
whether/which; (b) the combat cap is deliberate, not accidental.

## Recommendation

I agree with the revised recommendation in the feasibility notes (current
XMage as reference while building a bounded Witchcraft contribution), with one
reordering: **prototype the shared agent controls first**. Proper opponent
response decisions and complete combat choices gate this project's training
goal directly — the agent must control every meaningful decision before
recorded games are worth training on. The correctness work (coverage tests,
Rooms, impending/survival/manifest dread) only pays off if the agent-controls
problem fits Witchcraft's architecture cleanly. Finding that out after weeks
of card work instead of days would be the expensive ordering.

## Reproducibility

- `pip install python-mtg==0.1.1` (Python 3.12), no repo build required for
  these probes.
- Response probe: `Game({"alice": [...], "bob": [...]}, starting_hand=
  {"alice": ["Lightning Bolt"] + ["Mountain"]*6, "bob": [...]}, seed=1)`,
  drive with `game.push`, cast via `legal_moves` kind `"cast"`, observe
  `game.life()` / `game.hand("bob")` / `game.graveyard("bob")` before and
  after the turn-2 cast.
- Static findings: grep the cited files/lines in the installed package;
  `bridge_to_engine.py:252` in the source repo at `e35821c`.
