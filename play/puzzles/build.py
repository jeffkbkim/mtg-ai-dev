"""Build puzzles.jsonl: frozen Claude decisions from Playmat games, for comparing prompt versions (e.g. primer v1 vs v2).

Each puzzle is one recorded decision of a Claude seat (kind, prompt, obs, options, leaks as recorded), the seat's deck
file, the log that seat had before it (rebuilt from its earlier records the way ClaudePlayer.choose() writes it), the
original pick and reason, and our judgment: "acceptable" (option indices judged OK), "bad_choice" (bad puzzles only),
an optional "lenient" set (a looser reading, reported separately), and a short "why".

    python play/puzzles/build.py            # writes play/puzzles/puzzles.jsonl and prints each puzzle's options

The judgments are ours (read from the state the seat could see), not ground truth. Bad puzzles come from Jeff's
confirmed errors and from the per-turn review's "mistake" flags that we agreed with; controls are decisions v1 played
well. Game records live under ~/mtg-data/playmat-games (outside Git); the jsonl carries everything the runner needs.
"""
import json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from render import events, option_label  # noqa: E402

GAMES = Path.home() / "mtg-data" / "playmat-games"

# (id, type, date, game prefix, seat, idx, acceptable, bad_choice, lenient, source, why)
SPEC = [
    # ---- bad: v1 got these wrong ----
    ("bad-4741-87", "bad", "2026-10-23", "4741b72d", "B", 87, [3], 1, [0, 2, 3, 4], "Jeff confirmed; review mistake",
     "Sheltered by Ghosts host: Ragged Playmate is tapped and locked by Stay Hidden, Stay Silent (its non-targeting "
     "shuffle ignores ward), so the aura's +1/+0 and lifelink are wasted and the exile is fragile. The attacking Splitskin "
     "Doll with the Hospital Room counter [15] is the host (lenient: any creature not under the lock)."),
    ("bad-4741-127", "bad", "2026-10-23", "4741b72d", "B", 127, [0], 8, [0, 1, 2, 3, 4, 5, 6, 9], "Jeff confirmed; review questionable/mistake",
     "Attacking the only two flying blockers into an untapped 6/6 flying Demon, 0 cards in hand, while losing the race "
     "to the Demon and the Annex drain. Keep the Insects home (DONE): the ground attacks don't work either (lenient: anything but an Insect)."),
    ("bad-4741-128", "bad", "2026-10-23", "4741b72d", "B", 128, [0], 7, [0, 1, 2, 3, 4, 5, 6, 8], "Jeff confirmed; review mistake",
     "Second step of the same attack (one Insect already declared): adding the other flying Insect leaves no flying "
     "blocker for the Demon. DONE keeps one home (lenient: anything but the second Insect)."),
    ("bad-3c4b-30", "bad", "2026-10-24", "3c4b4d2c", "B", 30, [0], 1, None, "task (Jeff's game)",
     "Double block of the 3/3 Stalked Researcher (a defender) with Optimistic Scavenger, the Eerie counter engine, and "
     "Fear of Isolation: the Scavenger dies for a wall that can rarely attack. Taking 3 at 12 is fine (DONE); Fear of "
     "Isolation alone just dies, so it isn't acceptable either."),
    ("bad-4741-12", "bad", "2026-10-23", "4741b72d", "B", 12, [1], 4, None, "review mistake (section 3, colours)",
     "Land choice: Mountain still casts Glimmer Seeker ({2}{W}) or Surgical Suite and also allows Piggy Bank plus Turn "
     "Inside Out in one turn; Plains leaves one red source. Mountain is better in every line."),
    ("bad-4741-13", "bad", "2026-10-23", "4741b72d", "B", 13, [0], 2, None, "review mistake (section 3, sequencing)",
     "Casting summoning-sick Glimmer Seeker precombat taps all 3 lands, so the attack can't use Turn Inside Out against a "
     "Fear of Isolation block, and the opponent has 0 open mana. Go to combat first (PASS); cast after combat."),
    ("bad-6be3-10", "bad", "2026-10-23", "6be31dce", "A", 10, [0, 3, 4], 2, None, "review mistake (section 3, sequencing)",
     "Unsettling Twins precombat taps all 4 lands, so the face-down Patched Plaything can't attack with its {2}{W} flip "
     "up, against an opponent with 0 open mana. Attack first (PASS), or only spend 1 (Percussionist, equip) first."),
    ("bad-03df-21", "bad", "2026-10-23", "03df1d96", "B", 21, [2], 1, None, "review mistake (section 3, answers)",
     "Fear of Exposure taps all 5 lands, so Scorching Dragonfire (the exile answer to the recursive deathtouch, "
     "half-life Unstoppable Slasher) can't be cast this turn or on the opponent's. Dragonfire the Slasher now while the "
     "opponent is tapped out."),
    ("bad-4e6a-68", "bad", "2026-10-23", "4e6a2ebd", "B", 68, [2], 4, None, "review mistake (section 3, lands)",
     "Lakeside Shack enters tapped at these life totals either way. This turn's plan (Break Down the Door + a 2-drop) "
     "needs 5 mana, which the board has: play the Shack now and keep the Island for an untapped drop next turn."),
    # ---- control: v1 got these right ----
    ("ctl-c8d5-23", "control", "2026-10-24", "c8d5a0e5", "B", 23, [5, 6], None, None, "task",
     "Fear of Immobility's tap + stun: a flying deathtouch Insect token, the opponent's best attacker and blocker."),
    ("ctl-8ecc-71", "control", "2026-10-24", "8ecc3f2a", "B", 71, [6], None, [1, 2, 3, 4, 5, 6, 7], "task",
     "Lethal: Arabella's attack trigger drains for the number of creatures with power 2 or less (6) into 5 life. "
     "Attack with Arabella (lenient: any attacker first, DONE is the failure)."),
    ("ctl-4741-109", "control", "2026-10-23", "4741b72d", "B", 109, [0], None, None, "task",
     "No block on the 4/5 Bookworm at 20 life with opponent mana up: no single blocker survives and a gang block loses "
     "two creatures."),
    ("ctl-4741-0", "control", "2026-10-23", "4741b72d", "B", 0, [0], None, None, "mulligan",
     "Zero lands in the opening seven: mulligan."),
    ("ctl-8ecc-1", "control", "2026-10-24", "8ecc3f2a", "B", 1, [0], None, None, "mulligan",
     "Six lands and one 8-mana Room in an aggressive RW deck: mulligan."),
    ("ctl-03df-46", "control", "2026-10-23", "03df1d96", "B", 46, [0, 3], None, None, "removal target",
     "Scorching Dragonfire exiles: aim it at an attacking Unstoppable Slasher (either; both deathtouch half-life threats), "
     "not the Rat, Analyst or manifest."),
    ("ctl-18de-8", "control", "2026-10-23", "18ded83e", "B", 8, [1], None, None, "aggressive attack",
     "Slasher into an empty board with the opponent tapped out: 2 damage plus half their life. Must attack."),
    ("ctl-c636-33", "control", "2026-10-23", "c6361e31", "A", 33, [2, 3, 4], None, [1, 2, 3, 4], "lethal attack",
     "Opponent at 1 with two blockers: attack with the real attackers (8/7 trample Wickerfolk etc.). DONE is the failure."),
    ("ctl-8a33-84", "control", "2026-10-23", "8a33eb51", "A", 84, [1, 2, 3, 4, 5, 6], None, None, "lethal attack",
     "Opponent at 2 with two blockers against six attackers: alpha strike. DONE is the failure."),
    ("ctl-3faf-21", "control", "2026-10-23", "3fafcfc0", "B", 21, [2], None, None, "block",
     "Chump the Unstoppable Slasher (half-life on damage) rather than take it; Fear of the Dark has menace."),
]


def game_dir(date, prefix):
    (d,) = [p for p in (GAMES / date).iterdir() if p.name.startswith(prefix)]
    return d


def log_before(records, idx):
    """The log ClaudePlayer.choose() would hold right before decision idx (see ClaudePlayer.resume), including the
    lines for what changed since the previous record, and the last ATTACK/BLOCK (turn, kind) it self-checked."""
    log, prev, checked = [], None, None
    for r in records:
        if r.get("rule") or r.get("auto") == "own_stack" or r.get("leak_blocked"):
            continue  # answered by the service without the player
        g = r["obs"]["entries"][0]
        tag = f"(undone by {r['undone']}) " if r.get("undone") else ""
        log += [f"{tag}turn {g['turn']}: {line}" for line in events(prev, r["obs"])]
        prev = r["obs"]
        if r["idx"] == idx:
            return log, checked
        if "reason" in r and 0 <= r.get("choice", -1) < len(r["options"]):
            log.append(f"{tag}turn {g['turn']}: you chose \"{option_label(r['options'][r['choice']], r['obs']['entries'])}\" ({r['reason']})")
            if r["kind"] in ("ATTACK", "BLOCK"):
                checked = (g["turn"], r["kind"])
    raise KeyError(idx)


def build():
    out = []
    for pid, typ, date, prefix, seat, idx, acceptable, bad, lenient, source, why in SPEC:
        d = game_dir(date, prefix)
        records = [json.loads(l) for l in (d / f"seat-{seat}.jsonl").open()]
        (r,) = [x for x in records if x["idx"] == idx]
        assert r.get("source") == "claude" and "reason" in r, (pid, "not a Claude-asked decision")
        log, checked = log_before(records, idx)
        orig = r["choice"]
        if typ == "bad":
            assert orig not in acceptable and orig == bad, (pid, orig)
        else:
            assert orig in acceptable, (pid, orig)
        out.append({
            "id": pid, "type": typ, "source": source, "game": d.name, "date": date, "seat": seat, "idx": idx,
            "game_dir": str(d), "deck": str(d / f"deck-{seat}.dck"),
            "kind": r["kind"], "prompt": r["prompt"], "obs": r["obs"], "options": r["options"], "leaks": r["leaks"],
            "log": log, "checked_combat": checked,
            "original": {"choice": orig, "reason": r["reason"], "player": r["player"],
                         "self_check_first": (r.get("self_check") or {}).get("first_choice")},
            "bad_choice": bad, "acceptable": acceptable, "lenient": lenient, "why": why,
        })
        ents = r["obs"]["entries"]
        print(f"{pid} ({r['kind']}, orig {orig}): " + "; ".join(
            f"{'*' if i in acceptable else ''}{i}={option_label(o, ents)[:40]}" for i, o in enumerate(r["options"])))
    path = HERE / "puzzles.jsonl"
    path.write_text("".join(json.dumps(p) + "\n" for p in out))
    print(f"{len(out)} puzzles -> {path}")


if __name__ == "__main__":
    build()
