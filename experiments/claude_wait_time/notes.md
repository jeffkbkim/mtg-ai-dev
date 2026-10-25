# Where the Claude seat's time goes (2026-10-25)

Read-only analysis of 29 human-vs-Claude Playmat games (~/mtg-data/playmat-games, 2026-10-23..25), by
`wait_time.py`; its output is `results.md`. Time is the recorded `seconds` per decision (the Claude service's
wall clock from being asked to answering, including the self-check call when there is one). Decisions a take-back
superseded are dropped; windows answered without a model call (`auto`: pass_until, own_stack) are counted apart.

- 1,507 Claude decisions, 12,329 s (205 min); median 418 s of Claude time per game.
- Already skipped without a model call: 271 pass_until windows and 30 own-stack passes (301, i.e. 17% of windows).
- Priority is 54% of the time, attacks 23%, blocks 8% (the slowest, median 11 s), targets 7%.
- Claude's own precombat main with an empty stack is the biggest single bucket (30%): real decisions, 81% act.
- (a) PASS with no legal non-pass option: 0, as expected (Java answers those).
- (b) PASS with an opponent creature spell on the stack: 8 decisions, 0.5%.
- (c) Combat-window PASS: 178 decisions, 8.0%.
- (d) Claude's own main phases, all decision kinds: 44%.
- A cheap gate (PASS with at most one non-pass option, no opponent object on the stack, life > 8) covers 257
  decisions, 11.5% of the time. The stack entries carry no target info, so "nothing targets Claude's stuff" is
  approximated by "no opponent object on the stack".

Caveats: one Claude model/effort mix (Opus/Sonnet, low..high) is pooled; seconds include network and the
self-check; pass/act is from the chosen option's action (PASS/DONE).
