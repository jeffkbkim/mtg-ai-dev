"""Deck building for a drafted pool: 23 spells in the pool's best two colours and 17 basic lands.

A simple rule builder, not a model: each card is worth its 17lands games-in-hand win rate (train split; 0.5 when
unknown), the two colours whose best 23 playables are worth the most win, then the curve is kept sane (at least 14
creatures when the pool has them, at most 4 cards of mana value 6 or more) and lands follow the coloured pips.
Basic lands (and lands drafted from packs) are left in the sideboard; nonbasic lands aren't played.
"""
import itertools, re

from .brains import COLORS, GihBrain, card_info

BASICS = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}
SPELLS, LANDS = 23, 17
MIN_CREATURES, MAX_TOP = 14, 4

_gih = None


def _ratings():
    global _gih
    if _gih is None:
        _gih = GihBrain()
    return _gih


def build(set_code, pool):
    """pool: card names -> {"main": [names], "lands": {basic name: count}, "colors": "WU", "sideboard": [names]}"""
    info, gih = card_info(set_code), _ratings()
    value = {n: gih.gih(set_code, n) or 0.5 for n in set(pool)}
    playable = [n for n in pool if n in info and "Land" not in info[n]["types"]]

    def pick(colors):
        fits = sorted((n for n in playable if all(c in colors for c in info[n]["colors"])), key=lambda n: -value[n])
        main, rest = [], list(fits)
        # the best creatures first, so the deck has bodies; then the best of everything else
        for want_creature in (True, False):
            for n in list(rest):
                if len(main) >= (MIN_CREATURES if want_creature else SPELLS):
                    break
                if want_creature and "Creature" not in info[n]["types"]:
                    continue
                if info[n]["mana_value"] >= 6 and sum(info[m]["mana_value"] >= 6 for m in main) >= MAX_TOP:
                    continue
                main.append(n)
                rest.remove(n)
        return main, sum(value[n] for n in main) - 0.5 * max(SPELLS - len(main), 0)

    best = max((pick(a + b) + (a + b,) for a, b in itertools.combinations(COLORS, 2)), key=lambda t: t[1])
    main, _, colors = best
    pips = dict.fromkeys(colors, 0)
    for n in main:
        for c in colors:
            pips[c] += info[n]["cost"].count(c)
    lands_total = LANDS + max(SPELLS - len(main), 0)
    total = sum(pips.values()) or 1
    lands = {BASICS[c]: round(lands_total * pips[c] / total) for c in colors}
    first = BASICS[max(colors, key=lambda c: pips[c])]
    lands[first] += lands_total - sum(lands.values())
    rest = list(pool)
    for n in main:
        rest.remove(n)
    return {"main": main, "lands": {k: v for k, v in lands.items() if v > 0}, "colors": colors, "sideboard": rest}
