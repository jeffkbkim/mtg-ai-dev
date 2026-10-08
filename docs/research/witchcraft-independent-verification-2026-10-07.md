# Independent verification of Witchcraft boundary probes — 2026-10-07

This report independently re-verifies four Witchcraft boundary findings that
gate the engine decision: (1) opponent instant responses are driver-greedy,
(2) combat enumeration is capped at five attackers, (3) face-down observation
leaks printed power/toughness, and (4) later Room unlocking is unmodeled.
Every load-bearing claim below was checked against the primary
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

**Nuance not in the earlier report (refined by the runnable probe).** Whether
to respond and with which spell never reach a policy. Target selection is not
on the response path either: the response Bolt's target defaulted greedily
with zero `_choose` calls (verified dynamically — spies on both seats recorded
no `target`/`modes` calls while it resolved). Only a *modal* response's mode
choice would reach `_choose` (via `_choose_mode`), and the `_policy` dispatch
keys on the active player, so even that would consult the wrong seat's policy,
not the responder's.

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
see morphs' and manifested cards' stats. The redaction fix itself is small
(add the two relations to the set), but that only closes this identity leak —
it is not evidence that derived characteristics or gameplay involving
face-down cards are correct. Modeling the applicable face-down characteristics
is a separate requirement. I did not audit test coverage, so I make no claim
about whether a test covers this; the finding is the leak itself. Acceptance
checks for a real fix: changing an unknown face-down card's identity must not
change the opponent's observation, its visible base characteristics must be
correct, and its controller must retain only the knowledge they are entitled
to.

## 4. Rooms: later paid unlocking unmodeled — CONFIRMED (static)

`packages/mtg/bridge_to_engine.py:252` (source repo) maps "when you unlock
this door" to the enter-the-battlefield event of the door that was cast. There
is no path for paying to unlock the second door later in the game. This
matches the earlier audit's observation that Rooms can report no bridge
omissions despite missing behavior.

## Verdict on the earlier claims

All four findings confirmed. Two nuances added: (a) the response bypass covers
whether/which/target — target selection is not on the response path at all,
and only a modal response's mode choice would reach `_choose` (and the
`_policy` dispatch keys on the active player, not the responder);
(b) the combat cap is deliberate, not accidental.

## Recommendation

**Recommendation (proposal, not a recorded decision).** Use current XMage as
the reference engine while building a bounded Witchcraft contribution — but
**prototype the shared agent controls first**. Proper opponent response
decisions and complete combat choices gate this project's training goal
directly: the agent must control every meaningful decision before recorded
games are worth training on. The correctness work (coverage tests, Rooms,
impending/survival/manifest dread) only pays off if the agent-controls problem
fits Witchcraft's architecture cleanly. Finding that out after weeks of card
work instead of days would be the expensive ordering.

## Reproducibility

- `pip install python-mtg==0.1.1` (Python 3.12), no repo build required for
  these probes.
- Response probe: `experiments/response_probe.py` (`pip install
  python-mtg==0.1.1`, Python 3.12). It plays a deterministic seed=1 line:
  Alice bolts on turn 1 (Bob has no mana, so no response is possible —
  Bob 20→17), both sides hold on Bob's turn 1, Alice bolts on turn 2.
  It asserts Bob's Bolt fires in response (Alice 20→17, Bob 17→14, one Bolt
  in Bob's graveyard) and replays the line with recording spy policies on
  both seats, asserting the identical outcome with no policy call for the
  response decision itself (only the game's routine `attackers`/`blocks`
  checks appear). Mana note: the driver's mana pool has no public observable,
  so the probe logs each side's battlefield lands before/after; Bob's single
  Mountain is consistent with the single fired Bolt. (The three-Bolt
  observation in §1 used a richer setup; the probe's minimal setup confirms
  the same bypass mechanism — the response count follows from available
  mana.)
- Static findings: grep the cited files/lines in the installed package;
  `bridge_to_engine.py:252` in the source repo at `e35821c`.
