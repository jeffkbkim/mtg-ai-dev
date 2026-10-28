# FDN soak, 2026-10-28

First Foundations soak (`soak.py --set FDN`, random seat vs XMage AI, 17lands-style FDN decks rotating through all
286 cards). Stopped by the cloud's time limit after 242 of 300 runs: 968 games, all finished normally.

Problems, by runs affected:

- `LEAKS` (12 runs): all one false alarm. Juggernaut (a card) is also a creature type, so a library or hand
  Juggernaut matched an option of "Choose a creature type". **Fixed** (de89360): the leak check ignores a creature
  type's own choice option.
- `UNKEYED_ON_BOARD` (37) and `UNMAPPED_ABILITIES` (9): two cards build an ability while their effect applies, a new
  object every time, so it was neither printed nor found inside the card's effects: Fishing Pole's
  "{1}, {T}, Tap Fishing Pole: Put a bait counter on Fishing Pole." on the equipped creature, and Kellan, Planar
  Trailblazer's combat-damage trigger once it is a Detective. **Fixed**: `AbilityKeys.DYNAMIC` lists them, keyed
  "Fishing Pole#d0" and "Kellan, Planar Trailblazer#d0" (2 new entries in fdn_vocab.json; DSK vocab unchanged).
  The first 24 runs again with the fix: 0 unkeyed, 0 unmapped, 0 leaks.
- `UNMAPPED_CHOICES` (2): Omniscience's "Cast without paying its mana cost" alternative cost (a Special Guest), the
  same kind of gap as DSK's "{W}{U}{B}{R}{G}" alt cost. Open.
- `REJECTED` (111): moves the seat offers but XMage refuses, as in DSK soaks (random-play noise). Most common:
  Rogue's Passage's "{4}, {T}" (likely the land counting its own mana toward {4}), Eaten Alive, Run Away Together.
  Not fixed; a trained policy would waste some probability on them.
- 6 runs logged an H2 `EOFException` from XMage's card database with 3 JVMs in parallel; the games still finished.

New decision types: none beyond DSK's (kicker is asked as a yes/no USE, like other optional costs).
