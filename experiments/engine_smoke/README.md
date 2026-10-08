# DSK engine feasibility tests — October 7, 2026

## Results

Current XMage release `xmage_1.4.62V1` passed four complete games using the two committed 40-card DSK decks. Every loaded card name and count was checked against the input; no replacement or omission was permitted. The decks are synthetic mechanic-focused fixtures, not sampled human draft decks. Each includes 17 basic lands and 23 spells. They cover only a portion of DSK.

- Seeds supplied: 20261007 and 20261008; each run with UG and UW starting once.
- Terminal game lengths: 23, 26, 24, 26 turns.
- Game times: 4.393, 1.210, 1.147, 1.725 seconds; total 8.475 seconds.
- Warm database startup: 3.760 seconds; compilation plus process wall time: 13.198 seconds.
- Peak resident memory: 1,187,184,640 bytes (about 1.19 GB decimal / 1.11 GiB).
- Environment: this Mac, OpenJDK 23.0.1 arm64; one JVM, 256 MB initial / 3 GB maximum heap.
- Bots: built-in `ComputerPlayer7`, skill 2, one-second maximum thinking setting. These bots use engine-side search; this is **not** a direct-policy throughput measurement or a strength evaluation.
- No warnings, errors or exceptions in the successful run. An earlier harness attempt lacked match initialization and failed; the harness was corrected before the successful run.

Python compiled/launched the headless Java harness and recorded outcomes. It did not choose actions or consume model observations. Full Python policy integration, hidden-information correctness, exact seed replay and controlled per-mechanic rule tests remain unverified. Seeds are recorded inputs, not a claim of bit-for-bit repeatability. Four successful games do not prove every included mechanic was exercised or correct.

See `xmage-results-2026-10-07.json` for exact outputs and deck hashes.

## Important failed checks

The MageZero `v0.2.0-alpha` release contains an older XMage 1.4.58 bundle. Against the 271 nonbasic class names referenced by the inspected current DSK set registration, it lacks 22 classes. The UG test deck loaded only 36 cards, missing Say Its Name and Underwater Tunnel // Slimy Aquarium; the exact-deck check stopped immediately. Several other Rooms are absent. This comparison is source-class coverage, not an independently verified Arena draft-pool census.

A trial compilation of current missing classes against the old bundle failed due to API differences, including the RoomCard constructor and an absent generic effect. No partial overlay was used in the successful test. The current XMage release contains all 271 compared classes, but **the existing MageZero adapter has not been ported to it**.

`HiddenConfigProbe.java` reproduces a second released-bundle issue:

```text
hidden_info false -> opponentHand=true
hiddenInfo false -> opponentHand=false
```

The example YAML uses `hidden_info`; the actual loader expects `hiddenInfo` and defaults to seeing the opponent's hand. This probe checks configuration behavior without exposing game data. Even the correctly spelled flag is not proof of a safe complete observation/search pipeline.

## Reproduce XMage smoke

Download and extract the official current release outside Git, then run on macOS:

```sh
python3 experiments/engine_smoke/run.py /path/to/xmage/mage-server --output /tmp/mtg-dsk-results
```

Requires `java` and `javac`, and permission for H2's local database socket. The runtime directory must be writable for its database. The runner uses macOS `/usr/bin/time -l`. Logs and generated classes stay outside the repository. A 300-second timeout terminates the process group. No model dependencies or training are involved.

Release provenance:

- [Current XMage archive](https://github.com/magefree/mage/releases/tag/xmage_1.4.62V1): `mage-full_1.4.62-dev_2026-10-03_20-47.zip`; SHA256 `d256251ae41155638233c2cb20a7fec82f3f2dea7a468976691664c55e357b16`.
- [MageZero archive](https://github.com/WillWroble/MageZero/releases/tag/v0.2.0-alpha): SHA256 `c0242f186c312db81d0240d1e7479ce0f4306523ebec11d92d616a4f289926a3`.
- MageZero source inspected: `f7445e5ce9f42f4087bcf20c08e92ce1a71eec72`.
- DSK inventory source: XMage `8e11b9f0a8dfcbda5771e69e34e06925501955de`, `Mage.Sets/src/mage/sets/DuskmournHouseOfHorror.java`.

## Witchcraft contribution feasibility

The [latest inspected commit](https://github.com/yevbar/witchcraft/commit/e35821ce943fdd2313b0ece875341b0645b48f77) is September 12 Pacific / September 13 UTC. Its recent history includes concrete rules and coverage repairs. The project should not be dismissed as abandoned.

Using that source with Python 3.14.7, Lark 1.3.1, and the oracle corpus bundled in `python-mtg==0.1.1`, selected 276 records by the XMage DSK registration above. No optional spaCy dependency/model was installed. This limits the measurement to that parser configuration and corpus version. Results:

- All ability units parsed for **248/276** records (89.9%).
- Runtime bridge reported one or more dropped items for **143/276** records; 133 had no reported drops.
- Drop occurrences include 60 effects, 34 events, 31 unparsed units, 17 static effects and other categories. Multiple cards share patterns, and a card can have multiple drops; this is not 143 independent implementations.
- A clean drop list is insufficient: Rooms and most Overlords can produce no reported drops even though this audit has not established their full behavior. No claim of 133 fully supported cards follows from this result.
- Native runtime/full-game DSK behavior was not exercised by this parser/bridge audit.

Reproduce without editing tracked upstream source:

```sh
python experiments/engine_smoke/witchcraft_dsk_audit.py \
  /path/to/witchcraft /path/to/oracle_corpus.json \
  /path/to/mage/Mage.Sets/src/mage/sets/DuskmournHouseOfHorror.java \
  --output /tmp/witchcraft-dsk-audit.json
```

The earlier boundary probes remain in `docs/research/engine_audit_probes.py`.

## Proposed contribution sequence

Contributing DSK is plausible, but it includes both set mechanics and shared infrastructure. Prefer small independently reviewable changes:

1. **Coverage/observations:** checked DSK fixtures, explicit unsupported-state reporting, face-down observation invariance tests and fixes. Establish a reproducible source/native build before calling any rule change verified.
2. **Rooms:** choose either door when casting; enter with both doors locked when not cast; pay to unlock as a sorcery-speed special action; track characteristics and trigger unlocking/eerie correctly. This is a concrete vertical slice for an initial mechanic contribution.
3. **Other DSK mechanics:** test impending alternative costs/counters/type changes, survival's intervening condition, eerie, and manifest-dread choice/face-up/knowledge interactions. Reuse existing handlers where they pass tests.
4. **Agent control:** interruptible priority passing and choices for both seats, stack/trigger decisions, and complete combat selection without the subset cap. This is the largest shared architectural risk and should be scoped before promising full DSK training.
5. **Card audit and gameplay:** resolve remaining shared effect/parser gaps, then compare selected public outcomes against current XMage with fixed, explicitly supported decks. Unsupported cards must remain errors, never substitutions.

A useful first milestone is correct Rooms plus truthful coverage reporting, with a separate prototype proving opponent response control. Use XMage as a reference engine while contributing. No maintainer message, upstream issue or PR has been sent, and no Witchcraft production fix has been implemented in this task. Maintainer acceptance and the total effort remain unknown.
