import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "play"))
from eval_games import option_cards  # noqa: E402


def card(i, name, types, keywords=()):
    return {"kind": "card", "i": i, "name": name, "card_name": name, "types": types, "keywords": list(keywords)}


def test_option_cards_names_each_card_and_its_casting_speed():
    # Floodpits Drowner has flash in its rules text; a card in hand carries no keywords in the observation
    msg = {"obs": {"entries": [{"kind": "global"}, card(1, "Plains", "[Land]"), card(2, "Innocuous Rat", "[Creature]"),
                               card(3, "Floodpits Drowner", "[Creature]"),
                               card(4, "Say Its Name", "[Instant]")]},
           "options": [{"action": "PASS", "source": {}}, {"action": "PLAY_LAND", "source": {"entry": 1}},
                       {"action": "CAST", "source": {"entry": 2}}, {"action": "CAST", "source": {"entry": 3}},
                       {"action": "CAST", "source": {"entry": 4}}]}
    assert option_cards(msg) == [
        {"action": "PASS"},
        {"action": "PLAY_LAND", "name": "Plains", "types": "[Land]"},
        {"action": "CAST", "name": "Innocuous Rat", "types": "[Creature]", "speed": "sorcery"},
        {"action": "CAST", "name": "Floodpits Drowner", "types": "[Creature]", "speed": "instant"},
        {"action": "CAST", "name": "Say Its Name", "types": "[Instant]", "speed": "instant"},
    ]


def test_option_cards_ignores_a_source_that_is_not_a_card():
    msg = {"obs": {"entries": [{"kind": "global"}]}, "options": [{"action": "ACTIVATE", "source": {"entry": 0}}]}
    assert option_cards(msg) == [{"action": "ACTIVATE"}]
