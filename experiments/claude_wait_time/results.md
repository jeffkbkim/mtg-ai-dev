games 29, Claude decisions 1508, Claude seconds 12344 (205.7 min), per game median 427s, mean 426s
auto-answered windows (no model call): {'pass_until:my_main': 70, 'pass_until:end_of_turn': 153, 'pass_until:my_turn': 48, 'own_stack': 30}

By kind
| bucket | n | secs | % time | median s | % pass |
|---|---|---|---|---|---|
| priority | 864 | 6652 | 53.9 | 5.9 | 53 |
| attack | 305 | 2819 | 22.8 | 7.1 | 26 |
| other | 156 | 1104 | 8.9 | 5.7 | 3 |
| block | 74 | 951 | 7.7 | 11.4 | 30 |
| target | 109 | 819 | 6.6 | 6.2 | 10 |

Priority by turn / step group / stack
| bucket | n | secs | % time | median s | % pass |
|---|---|---|---|---|---|
| ('own', 'Precombat Main', 'empty') | 414 | 3687 | 29.9 | 6.4 | 19 |
| ('own', 'combat', 'empty') | 127 | 702 | 5.7 | 5.1 | 96 |
| ('own', 'Postcombat Main', 'empty') | 76 | 575 | 4.7 | 5.9 | 51 |
| ('own', 'Upkeep', 'empty') | 51 | 331 | 2.7 | 5.6 | 96 |
| ('own', 'Draw', 'empty') | 16 | 231 | 1.9 | 7.6 | 62 |
| ('opp', 'combat', 'empty') | 39 | 223 | 1.8 | 5.2 | 92 |
| ('own', 'Precombat Main', 'own') | 42 | 199 | 1.6 | 4.7 | 100 |
| ('opp', 'Precombat Main', 'opp ability') | 23 | 161 | 1.3 | 5.8 | 87 |
| ('opp', 'Precombat Main', 'opp noncreature spell') | 19 | 129 | 1.0 | 6.3 | 95 |
| ('own', 'combat', 'own') | 12 | 80 | 0.6 | 6.4 | 100 |
| ('opp', 'End Turn', 'empty') | 10 | 71 | 0.6 | 7.0 | 60 |
| ('own', 'combat', 'opp noncreature spell') | 3 | 44 | 0.4 | 12.7 | 67 |
| ('opp', 'Precombat Main', 'opp creature spell') | 5 | 38 | 0.3 | 6.8 | 80 |
| ('opp', 'End Turn', 'opp ability') | 3 | 31 | 0.3 | 5.4 | 33 |
| ('opp', 'combat', 'opp ability') | 4 | 26 | 0.2 | 6.1 | 50 |
| ('opp', 'Postcombat Main', 'opp ability') | 3 | 17 | 0.1 | 5.8 | 100 |
| ('own', 'Precombat Main', 'opp noncreature spell') | 2 | 17 | 0.1 | 8.6 | 100 |
| ('own', 'End Turn', 'opp creature spell') | 1 | 13 | 0.1 | 12.9 | 100 |
| ('own', 'End Turn', 'empty') | 2 | 13 | 0.1 | 6.4 | 100 |
| ('own', 'End Turn', 'own') | 2 | 12 | 0.1 | 6.0 | 100 |
| ('opp', 'Postcombat Main', 'opp creature spell') | 2 | 11 | 0.1 | 5.4 | 100 |
| ('own', 'Draw', 'opp ability') | 2 | 8 | 0.1 | 4.0 | 100 |
| ('opp', 'combat', 'opp noncreature spell') | 1 | 7 | 0.1 | 6.6 | 100 |
| ('own', 'combat', 'opp creature spell') | 1 | 6 | 0.1 | 6.2 | 100 |
| ('own', 'combat', 'opp ability') | 1 | 5 | 0.0 | 5.5 | 100 |
| ('own', 'First Combat Damage', 'empty') | 1 | 5 | 0.0 | 5.1 | 100 |
| ('opp', 'combat', 'own') | 1 | 5 | 0.0 | 4.9 | 100 |
| ('own', 'Postcombat Main', 'own') | 1 | 4 | 0.0 | 3.9 | 100 |

Priority: pass or act, and non-pass options
| bucket | n | secs | % time | median s | % pass |
|---|---|---|---|---|---|
| ('act', 3) | 247 | 2352 | 19.1 | 7.4 | 0 |
| ('PASS', 1) | 326 | 1835 | 14.9 | 5.3 | 100 |
| ('act', 1) | 83 | 842 | 6.8 | 6.4 | 0 |
| ('act', 2) | 74 | 658 | 5.3 | 7.1 | 0 |
| ('PASS', 2) | 80 | 530 | 4.3 | 5.6 | 100 |
| ('PASS', 3) | 54 | 435 | 3.5 | 5.6 | 100 |

PASS with exactly one non-pass option, what that option was: {'Spell': 224, 'Activated': 71, 'Special Action': 31}

Highlights
- (a) PASS with no legal non-pass option: 0 decisions, 0s (0.0% of Claude's time)
- (b) PASS with an opponent creature spell on the stack: 8 decisions, 58s (0.5% of Claude's time)
- (c) combat-window PASS: 178 decisions, 991s (8.0% of Claude's time)
- (d) Claude's own main phases (all kinds): 677 decisions, 5470s (44.3% of Claude's time)
- Haiku-gate candidates (PASS, <=1 non-pass option, no opponent object on the stack, life > 8): 257 decisions, 1413s (11.4% of Claude's time)
