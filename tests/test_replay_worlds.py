"""turn_replay's alternative readings of a turn: the consistent option set and the other worlds' later decisions."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("polars")  # turn_replay needs the data group: uv run --group data pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "seventeenlands"))
from turn_replay import alternative_rows, consistent_sets, option_indices, world_counts, world_share  # noqa: E402


OPTIONS = [{"label": "PASS"}, {"label": "Play land | Plains | Play Plains"}, {"label": "Spell | Rat | Cast Rat"}]


def row(point, choice, step="Precombat Main", at=0, options=OPTIONS, **kw):
    return {"point": point, "choice": choice, "step": step, "at": at, "fixed_label": None, "options": options, **kw}


# Turn: main 1 is choice point 0 (play the land now, option 1, or wait, option 0). The reproducing path played it.
POINTS = [{"point": "A PRECOMBAT_MAIN play", "alternatives": 2, "ambiguous": True, "fully_probed": True}]
# The departure "wait" also reproduced: main 1 passes, then main 2 plays the land (a decision with no choice point).
WORLDS = {(0, 1): [row(None, 0, "Upkeep"), row(0, 0), row(None, 2, "Postcombat Main", at=1)]}


def test_consistent_sets_lists_the_other_reproducing_options():
    assert consistent_sets(POINTS, WORLDS) == {0: {"PASS"}}


def test_consistent_sets_skips_points_not_fully_probed():
    partly = [{**POINTS[0], "fully_probed": False}]
    assert consistent_sets(partly, WORLDS) == {}


def test_alternative_rows_keep_only_decisions_after_the_departure():
    rows = alternative_rows(POINTS, WORLDS)
    assert [(r["step"], r["choice"]) for r in rows] == [("Postcombat Main", 2)]
    assert rows[0]["world"] == {"departs_at": 0, "alternative": 1, "n_worlds": 2}
    assert rows[0]["world_share"] == 0.5
    assert "fixed_label" not in rows[0]


def test_alternative_rows_drop_answers_the_replay_fixes_itself():
    worlds = {(0, 1): [row(0, 0), row(None, 0, "Draw", fixed_label="not_recorded"), row(None, 2, "Postcombat Main")]}
    assert [r["step"] for r in alternative_rows(POINTS, worlds)] == ["Postcombat Main"]


def test_unambiguous_points_give_no_set_and_no_worlds():
    unique = [{**POINTS[0], "ambiguous": False}]
    assert consistent_sets(unique, {}) == {} and alternative_rows(unique, {}) == []


def test_world_share_halves_after_each_two_way_split():
    n = world_counts(POINTS + [{**POINTS[0]}], {(0, 1): [row(0, 0)], (1, 1): [row(1, 0, at=1)]})
    assert n == {0: 2, 1: 2}
    assert [world_share(at, n) for at in (0, 1, 2)] == [1.0, 0.5, 0.25]  # before, between and after the splits


def test_opponent_departures_do_not_split_the_users_share():
    """A departure at the opponent's choice point (no user row at that point) writes nothing, so it isn't a split."""
    opp = [{**POINTS[0], "point": "B DECLARE_BLOCKERS play"}]
    assert world_counts(opp, {(0, 1): [row(None, 0, at=1)]}) == {}


def test_option_indices_follow_labels_not_the_other_attempts_order():
    """XMage can list options in another order on another attempt: the set is matched by label."""
    reordered = [OPTIONS[1], OPTIONS[0], OPTIONS[2]]
    other = {(0, 1): [row(0, 0, options=reordered)]}       # the departure picked index 0 = Plains in its own order
    labels = consistent_sets(POINTS, other)[0]
    assert labels == {"Play land | Plains | Play Plains"}
    assert option_indices(row(0, 0), labels) == [0, 1]       # this row's own PASS (its choice) and Plains


def test_option_indices_refuse_a_label_the_row_does_not_offer():
    assert option_indices(row(0, 0), {"Spell | Ghost | Cast Ghost"}) is None
