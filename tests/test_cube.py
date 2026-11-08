"""Arena Powered Cube support in the Claude player: deck set, system prompt, card text, pool, facts."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "play"))

import facts  # noqa: E402
from players import deck_set, system_prompt  # noqa: E402
from render import card_text, load_card_text, render  # noqa: E402

DECKS = ROOT / "engine/xmage/decks/cube-2025"


def test_cube_decks_are_cube_and_others_unchanged():
    assert deck_set(DECKS / "cube_00.dck") == "CUBE"
    assert deck_set(ROOT / "engine/xmage/decks/dsk_ug.dck") == "DSK"


def test_cube_prompt_has_cube_rules_primer_and_reminder_text():
    texts = load_card_text()
    s = system_prompt(DECKS / "cube_00.dck", texts, facts=True)
    assert "Arena Powered Cube (CUBE) Limited" in s
    assert "never used by the automatic payment" in s
    assert "## Arena Powered Cube primer" in s
    assert "Duskmourn" not in s


def test_set_files_win_over_the_cube_for_shared_cards():
    # the Cube's dump of Unholy Heat differs only in rarity; DSK's own file must win
    assert load_card_text()["Unholy Heat"]["rarity"] == "Mythic"


def test_double_faced_cards_show_both_faces_and_loyalty():
    t = load_card_text()
    fable = card_text(t["Fable of the Mirror-Breaker"])
    assert "other face: Reflection of Kiki-Jiki" in fable
    assert "loyalty 4" in card_text(t["Chandra, Torch of Defiance"])


def _global(**kw):
    g = {"kind": "global", "turn": 2, "step": "PRECOMBAT_MAIN", "my_turn": True, "my_life": 20, "opp_life": 20,
         "my_hand": 5, "opp_hand": 6, "my_library": 30, "opp_library": 30, "my_graveyard": 0, "opp_graveyard": 0,
         "stack_size": 0, "lands_played": 1}
    g.update(kw)
    return g


def test_mana_pool_is_shown_only_when_there_is_some():
    msg = {"kind": "PRIORITY", "prompt": "priority", "options": [{"label": "PASS", "kind": "PASS"}],
           "obs": {"entries": [_global(my_pool="{B}{B}{B}")], "edges": []}}
    assert "Mana in your pool: {B}{B}{B}" in render(msg, [], ())
    msg["obs"]["entries"] = [_global()]
    assert "Mana in your pool" not in render(msg, [], ())


def test_opponent_tricks_line_only_in_dsk_games(monkeypatch):
    seen = []
    monkeypatch.setattr(facts, "facts", lambda msg: seen.append(facts._OPP_TRICKS_ON[0]) or [])
    facts.facts_block({}, "CUBE")
    facts.facts_block({}, "DSK")
    assert seen == [False, True]
    assert facts._OPP_TRICKS_ON[0] is True
