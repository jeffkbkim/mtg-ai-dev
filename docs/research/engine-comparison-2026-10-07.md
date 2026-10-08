# MTG engine comparison — 2026-10-07

For this project's first target: DSK Limited, two players, direct-policy gameplay, Python model/training code, M4 Mac mini with 16 GB RAM.

**Runtime follow-up:** [DSK tests and Witchcraft contribution scope](../../experiments/engine_smoke/README.md) supersede the untested integration assumptions below. Current XMage completed four exact-deck games, but MageZero's packaged release lacks 22 compared DSK classes and has a reproduced hidden-information config mismatch. Its ready-made integration advantage is therefore weaker than the initial source review suggested.

## Recommendation

**Keep XMage as the first integration candidate; Forge is a credible second choice. Do not commit to Witchcraft as the full DSK environment yet.** This is a recommendation, not a completed integration decision.

The search found other Python engines, but none demonstrated a better combination of DSK correctness and agent control. Witchcraft has an appealing Python API and a working macOS wheel. However, missing Room actions, automatic response choices, restricted combat enumeration, and an observation-redaction failure make adoption an engine-development project. That could be enjoyable if building an engine becomes an explicit goal; it competes with learning model design and training.

For a strict no-Java requirement, a separate evaluation of the Rust Forge port ManaBrew is worth considering. It is not a Python engine or a verified DSK replacement. Python model code can use a native engine, just as Witchcraft itself uses a compiled backend.

## What was measured

Source checkouts were pinned to:

- [XMage](https://github.com/magefree/mage/tree/8e11b9f0a8dfcbda5771e69e34e06925501955de): `8e11b9f0a8dfcbda5771e69e34e06925501955de`.
- [Forge](https://github.com/Card-Forge/forge/tree/e7fca2893131cbad650416f9e2e5fef7e6efcdc6): `e7fca2893131cbad650416f9e2e5fef7e6efcdc6`.
- [Witchcraft](https://github.com/yevbar/witchcraft/tree/e35821ce943fdd2313b0ece875341b0645b48f77): `e35821ce943fdd2313b0ece875341b0645b48f77`.
- [Hyperdraft](https://github.com/discordwell/Hyperdraft/tree/1e17b41f05a134b33ebcc00f93b84be14a0a3363): `1e17b41f05a134b33ebcc00f93b84be14a0a3363`.

Counts use cloc 2.06, excluding blank/comment lines. These are selected source modules, not a measured minimal dependency closure or equivalent-feature implementations.

### XMage

- `Mage/src/main`: **206,969 Java code lines**, 3,755 files. This includes generic effects, abilities, keywords and rules infrastructure.
- `Mage.Common/src/main`: **11,193** additional Java lines, 131 files; shared infrastructure is reported separately.
- `Mage.Sets/src/mage/cards`: **1,502,285** Java lines, 32,498 files, for the entire per-card library.
- `Mage.Sets/src/mage/sets`: **112,886** additional set-registration lines, 589 files.
- The DSK registration references **271 unique nonbasic card classes totaling 12,422 code lines**. Five basic-land classes are in the core. This registration is not an audited list of the exact Arena draft pool; it also does not measure all helper/token dependencies.
- UI, server, AI plugins and tests are outside these core counts.

### Forge

- `forge-game/src/main`: **96,337 Java code lines**, 819 files.
- `forge-core/src/main`: **19,397**, 153 files.
- Combined: **115,734 Java code lines** in 972 files, excluding AI, UI and tests.
- All `forge-gui/res/cardsfolder` scripts: **34,074 text files**, **304,646 nonblank, non-`#`-comment lines**. These contain card metadata and Oracle text as well as executable script declarations; they are not equivalent to Java LOC.

### Witchcraft

- Runtime/API/agents in `packages/mtg`, `effect_handlers`, `engine_handlers`, excluding test files: **20,108 Python code lines**, 131 files.
- Interpreter/card parser/build pipeline: **19,088 Python lines**, 122 files.
- Python tests: **24,291 lines**, 262 files.
- Other Python tools and integrations: **7,638 lines**, 57 files.
- Total first-party Python: **71,125 lines**, 572 files.
- Datalog `.dl` files: **17,367 code lines**, 107 files. This includes generated/combined outputs, so it is not a count of unique hand-maintained rules. Counted with C-style comment handling using `--force-lang=C,dl`.
- Also present: 1,796 Java lines in the Forge integration and 166 C++ lines. The vendored Soufflé submodule was excluded.

Thus “about 20k Python runtime LOC” is a useful size description, but “the entire engine is 20k lines of pure Python” is inaccurate. Its rule-evaluation backend uses Soufflé-generated native code. The Python total excludes native dependencies; the Datalog total contains duplication.

Reproduce the core counting scopes with:

```sh
perl cloc-2.06.pl --include-lang=Java --by-file --json forge-game/src/main forge-core/src/main
perl cloc-2.06.pl --include-lang=Java --by-file --json Mage/src/main Mage.Common/src/main
perl cloc-2.06.pl --include-lang=Java --by-file --json Mage.Sets/src/mage/cards Mage.Sets/src/mage/sets
perl cloc-2.06.pl --skip-uniqueness --force-lang=C,dl --exclude-dir=.git,third_party --by-file --json .
```

For Witchcraft, classify Python files with a `tests`/`test` path component, a `test_` basename prefix or `_test.py` suffix as tests first, then classify remaining paths into the modules above. Exclude downloaded/generated untracked files when repeating the count.

## XMage: strongest existing Python training path

**Advantages**

- Dedicated source implementations exist for Rooms, manifest dread and impending. Tests include `RoomCardTest`, `ManifestTest` and `ImpendingTest`. The manifest-dread effect explicitly asks the player which card to manifest.
- [MageZero](https://github.com/WillWroble/MageZero) supplies a Python training stack connected to an XMage fork. [DraftZero](https://github.com/danieljbrooks/draft-zero) extends that route to Limited. Its current documented format is FDN, not a validated DSK integration.
- Existing opponents and rule infrastructure provide a starting point for actual gameplay evaluation.

**Costs and uncertainties**

- Java remains a runtime dependency. A Python wrapper still has to represent every relevant decision and filter observations correctly.
- Fork versions matter: latest upstream DSK implementations do not establish that a pinned MageZero bundle behaves identically.
- Existing agent encoders/search must be audited for hidden information, action truncation and reproducibility. Engine correctness does not automatically make a particular ML adapter correct.
- No XMage build, DSK game, throughput benchmark or memory profile was executed in this audit. Finding implementations and tests is evidence of coverage, not proof of all interactions.

**Expected ownership:** integration, observation/action validation, and occasional upstream bugs. Reuse the adapter concepts without adopting someone else's model or search architecture.

Relevant source: [manifest dread](https://github.com/magefree/mage/blob/8e11b9f0a8dfcbda5771e69e34e06925501955de/Mage/src/main/java/mage/abilities/effects/keyword/ManifestDreadEffect.java), [Room tests](https://github.com/magefree/mage/blob/8e11b9f0a8dfcbda5771e69e34e06925501955de/Mage.Tests/src/test/java/org/mage/test/cards/cost/splitcards/RoomCardTest.java).

## Forge: mature rules and reusable card scripts

**Advantages**

- Smaller measured core, with card definitions separated into a readable domain-specific script format.
- Explicit implementations exist for manifest dread, unlocking Rooms, and impending; DSK card scripts use them.
- The manifest-dread implementation delegates the top-two choice to the player controller.
- Existing AI supplies potential evaluation opponents. Core module dependency declarations separate `forge-game` from the graphical clients, although a practical headless harness still needs initialization and card loading.

**Costs and uncertainties**

- Still Java. Building a general Python agent interface is more work than importing a package.
- `PlayerController` exposes a broad callback interface: 113 matching `public abstract` declaration lines at the inspected commit. A correct integration must cover targeting, ordering, optional effects, payment and other choices, not just cast/attack/pass.
- It is not established that the smaller source tree is faster or easier to adapt than XMage for this project.
- No Forge build or DSK runtime test was run here.

**Expected ownership:** more initial adapter work than the existing XMage training route, but relatively little reason to rewrite game rules.

Relevant source: [manifest dread](https://github.com/Card-Forge/forge/blob/e7fca2893131cbad650416f9e2e5fef7e6efcdc6/forge-game/src/main/java/forge/game/ability/effects/ManifestDreadEffect.java), [Room card script](https://github.com/Card-Forge/forge/blob/e7fca2893131cbad650416f9e2e5fef7e6efcdc6/forge-gui/res/cardsfolder/b/bottomless_pool_locker_room.txt), [controller interface](https://github.com/Card-Forge/forge/blob/e7fca2893131cbad650416f9e2e5fef7e6efcdc6/forge-game/src/main/java/forge/game/player/PlayerController.java).

## Witchcraft: convenient API, consequential gaps

**What worked**

- Installed the published `python-mtg==0.1.1` macOS wheel in an isolated temporary environment, imported `mtg`, created a game with Mountain-only decks, obtained legal moves and played a Mountain using the in-process native backend.
- Source includes a manifest-dread handler with a choice hook and substantial rules tests. It is more than a toy combat simulator.
- A Python-facing `Game`, legal-move, push/pop interface is attractive for experimenting.

**What prevents a recommendation for full DSK today**

1. **Rooms are incomplete.** The bridge explicitly models the initially cast door's unlock trigger as entering the battlefield and says later paid unlocking is unmodeled. DSK depends on later unlocking and fully-unlocked triggers.
2. **Agent response control is incomplete.** `env.to_move` returns the active player except during blocking, even when `has_priority` identifies the opponent. `Game` documents that the opponent-turn priority interface is not modeled. There IS stack resolution: `_cast_instant_response` greedily chooses the first castable instant internally. That is not a normal response decision offered to the opposing learned policy through `legal_moves`.
3. **Combat options are deliberately restricted.** With six unrestricted eligible attackers, `_attack_options` offers eight subsets rather than all 64. Restricting the policy this way prevents it from learning legal multi-creature attacks omitted by the interface. A sequential selection API could avoid enumerating all subsets without losing choices.
4. **Observation redaction needs repair/audit.** A synthetic boundary test that changes only an opponent's unknown face-down card's printed power/toughness changes the output of `observe`. It preserves those hidden printed facts. This is not a complete-game demonstration or a claim that native rules calculate face-down combat stats incorrectly.

The last three points have executable failing boundary probes in `engine_audit_probes.py`. Rooms are a documented source limitation. Source references: [bridge](https://github.com/yevbar/witchcraft/blob/e35821ce943fdd2313b0ece875341b0645b48f77/packages/mtg/bridge_to_engine.py), [Game API](https://github.com/yevbar/witchcraft/blob/e35821ce943fdd2313b0ece875341b0645b48f77/packages/mtg/game.py), [environment](https://github.com/yevbar/witchcraft/blob/e35821ce943fdd2313b0ece875341b0645b48f77/packages/mtg/engine/env.py), [driver](https://github.com/yevbar/witchcraft/blob/e35821ce943fdd2313b0ece875341b0645b48f77/packages/mtg/driver.py), [observation filter](https://github.com/yevbar/witchcraft/blob/e35821ce943fdd2313b0ece875341b0645b48f77/packages/mtg/engine/observe.py).

The installed July wheel is separate from the inspected source commit. A latest-source handler-test attempt stopped because the generated `datalog/cards.dl` was absent. The current native backend and full upstream suite were not built/run. The wheel smoke test does not validate current-source fixes or full DSK support. Likewise, the [article's Arena demonstration](https://yev.bar/magic) is not a test of complete simulator fidelity.

**Expected ownership:** Python API integration plus priority/decision-loop work, observation repair, mechanic completion and a card-by-card DSK audit. This is a substantially broader commitment.

## Other Python alternatives

- **Hyperdraft:** the most relevant additional Python candidate found. Its DSK module loads 277 card definitions and has explicit mechanic modules. Ran `test_phase5b_dsk_impending.py`, `test_manifest_dread.py`, and `test_rooms.py`: **25 passed**. However, its manifest-dread handler always manifests the first of the top two cards, Rooms default to the first door, and impending eligibility stores an erroneous once-per-game flag on a shared card definition. A boundary probe reproduces that marking one copy as used disables impending for a second copy. Thus passing its current tests does not demonstrate DSK fidelity. [Impending source](https://github.com/discordwell/Hyperdraft/blob/1e17b41f05a134b33ebcc00f93b84be14a0a3363/src/engine/impending.py), [manifest handler](https://github.com/discordwell/Hyperdraft/blob/1e17b41f05a134b33ebcc00f93b84be14a0a3363/src/engine/face_down.py), [Rooms](https://github.com/discordwell/Hyperdraft/blob/1e17b41f05a134b33ebcc00f93b84be14a0a3363/src/engine/rooms.py). Compare the [official DSK mechanics](https://magic.wizards.com/en/news/feature/duskmourn-house-of-horror-mechanics).
- **Forkei/mtg-ai:** Python simulator and training scaffold, but its own [roadmap](https://github.com/Forkei/mtg-ai/blob/8bde95b28d195df488b990afa5bf6613e2f8cb42/docs/ROADMAP.md) leaves opponent-turn instant decisions, hierarchical targeting and activated abilities in the RL action space incomplete. Not a demonstrated full DSK alternative.
- **open-mtg:** the [README](https://github.com/hlynurd/open-mtg) describes only lands and sorcery-speed effects as supported.
- **ManaClash:** its [README](https://github.com/fregaham/manaclash) targets Python 2.6 and a subset of Eighth Edition. Not a current DSK foundation.

This is a search result, not proof that no suitable Python project exists anywhere.

## Performance and the no-Java option

No apples-to-apples DSK benchmark was run. LOC, language and README game rates cannot establish training throughput or RAM requirements on the M4.

DraftZero's author reports an [M1 Pro benchmark](https://github.com/danieljbrooks/draft-zero/blob/main/docs/015-rules-engine-comparison.md) of random FDN play at about 45 turns/s for its XMage fork versus 20–23 for Forge. Those are their measurements on particular versions/workloads, not ours or DSK projections. Their documentation also identifies adapter/search issues involving hidden information and reproducibility. Direct-policy play avoids the repeated search cost, but not the need to validate observations and actions.

[ManaBrew](https://github.com/witchesofthehill/manabrew) is a Rust Forge port with a parity harness against Java Forge. Upstream explicitly calls it pre-release and says broad Rust card coverage remains in progress. Its reference/testing workflow still uses Java. It merits a separate DSK/API audit if a JVM at training runtime is unacceptable, but it is not a drop-in Python answer. No local build or test was attempted.

A second search also checked Python-facing native alternatives:

- [Arcana](https://github.com/levineuwirth/arcana) has Rust rules and PyO3/Gymnasium bindings. Its [October 6 audit](https://github.com/levineuwirth/arcana/blob/main/docs/audits/2026-10-06.md) explicitly says catalog access from Python and an action encoder still block the intended training path, and identifies engine gaps for modal/X spells, Vehicles and other mechanics. The large generated card count does not establish DSK correctness. Not locally built or tested.
- [mtg-kernel](https://github.com/jackmaiorino/mtg-kernel) has a Rust engine, JSONL environment and Python training stack; its README explicitly says running it does not require Java. That addresses the runtime preference, but this audit did not establish complete DSK coverage. It remains a candidate for a separate card/mechanic audit, not a verified replacement.
- [Argentum](https://github.com/chrismaghuhn/argentum-engine) also has Python ML work, but its engine is Kotlin. It does not remove the JVM from the architecture.

## Why DSK helps but does not make a port small

Restricting the card pool removes the need to implement tens of thousands of unrelated cards. The ~12.4k LOC of XMage's DSK nonbasic card classes illustrates that benefit.

However, those classes invoke a shared system for priority, stack resolution, choices, targets, zones, replacement effects, continuous characteristics, triggers, combat and hidden information. DSK itself needs both special actions and ordinary stack interactions, face-down knowledge, changing characteristics and delayed effects. A card-class count cannot tell us how much of the shared engine can safely be removed. Porting requires preserving behavior and validating interactions, not merely translating Java syntax.

## Concrete next decision

Before choosing permanently, run two fixed DSK 40-card decks through an XMage Python adapter and validate:

- Actual Arena-pool card coverage, with unsupported cards reported rather than replaced.
- Both Room doors, later unlocking, eerie, impending and manifest-dread choices.
- Agent-controlled responses, targets, optional effects and unrestricted legal combat choices.
- Seat-specific observations invariant under changes to unknown opponent cards and future draws.
- Seed/replay behavior, terminal outcomes, decisions/s, games/s and peak memory with a small worker count.

Use the same fixtures if evaluating Forge or repairing Witchcraft. Leave model, forward-pass, loss and training-loop implementation to the user.

## Audit reproduction and limits

Python probes use Python 3.14.7 free-threaded, pytest 9.1.1, pydantic 2.13.5 and the pinned source checkouts. `python-mtg==0.1.1` was installed separately for the wheel smoke test; the probes assert that the Witchcraft import comes from its source checkout.

```sh
WITCHCRAFT_ROOT=/path/to/pinned/witchcraft \
HYPERDRAFT_ROOT=/path/to/pinned/Hyperdraft \
python -m pytest -q docs/research/engine_audit_probes.py --tb=short
```

Observed: **4 failed**, for the documented unmet requirements. These are intentionally failing audit artifacts, not fixes or a passing project regression suite. The attack test stubs the backend's eligibility answer; other tests exercise Python boundary functions directly. Hyperdraft's probe mutates the same impending-used flag as its cast path without simulating payment/resolution. No test here is a complete DSK game. The repository has no configured type checker or application test suite yet; the probe file was syntax-checked separately.
