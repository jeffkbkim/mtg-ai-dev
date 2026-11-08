# Arena Powered Cube decks (2025 run)

40 decks of strong 17lands drafters from the 2025 Arena Powered Cube (Bo1 Premier Draft, Oct 30 - Nov 19 2025),
written by `play/cube_deck_pool.py` from `/mnt/project-files/data/17lands/cube/`. Of 3,451 eligible decks, the
following were chosen:

- the drafter's long-run win-rate bucket is at least 0.60 and they played 100 or more games;
- the deck is the draft's most-played build, played at least 3 times, with exactly 40 cards;
- every card is one XMage 1.4.62 has (it lacks the six Arena-only cube cards in `CubeList.MISSING`);
- highest drafter bucket first, at most 3 decks per main-colour combination.

`manifest.json` has each deck's draft id, colours, drafter bucket and its record with this build.

`cube_NN.plan.md` is a short game plan for each deck, written once by Claude (Opus, medium effort) from the deck
list. `play/players.py` puts it at the end of the seat's system prompt.

Companions in a drafter's sideboard are not used, and the 17lands sideboards are not kept.
