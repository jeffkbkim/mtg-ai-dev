# Claude misplays Jeff reported in Playmat games

One entry per report. Games are under `~/mtg-data/playmat-games/<date>/<game id>/`; Claude's decisions are in its
seat file (`seat-A.jsonl` or `seat-B.jsonl`) with the prompt, facts, reason and self-check.

Categories: **math** (wrong arithmetic about the board), **missing facts** (the facts block left out something that
decided it), **tricks** (didn't consider the opponent's instant-speed cards), **conservative attack**,
**not a misplay** (the report doesn't hold up on the record).

| Date (ET) | Game | Turn | What happened | Category | Fix | Status |
|---|---|---|---|---|---|---|
| 2026-10-31 | `2026-10-31/5b2863bd-d729-4528-9b70-3008f56e0844` (Claude 2 WB) | 5 | Orphans of the Wheat 2/1 attacked into House Cartographer 2/2 and Claude cast Shardmage's Rescue (+1/+1) after the block, believing the 3/2 survives 2 damage. | math | Trick-aware facts: Claude's own pump tricks with the post-trick fight result on attacks, blocks and combat in progress (982a176, 9b5fb10, 4eb953b). | live 2026-11-02 21:00 ET |
| 2026-10-31 | `2026-10-31/6399b3ec-9cd0-49ba-929b-abc2e19838b5` (Claude 4 BG) | 15 | Triple-blocked Primo 7/7 with 7/6 + 6/5 + 3/3. Jeff cast Horrid Vigor (deathtouch + indestructible): all three blockers died, Primo lived. Claude read the attack as a trick but only considered pumps and removal; the facts are board-only. | tricks | Facts line listing the DSK instant-speed tricks the opponent could cast from their land colours and open mana, plus "against deathtouch/indestructible every extra blocker is an extra loss". | live 2026-11-02 21:00 ET |
| 2026-10-31 | `2026-10-31/6399b3ec-9cd0-49ba-929b-abc2e19838b5` (Claude 4 BG) | 22 | Didn't attack ("should have attacked"). Spineseeker Centipede was summoning sick, so Innocuous Rat 1/1 was the only possible attacker, into an untapped Glimmer 1/1, with Claude at 4 library cards. Claude: no lethal, and the Rat's death manifest would mill 2 of its 4 cards. | not a misplay (Centipede couldn't attack); Rat attack marginal | None needed for the Centipede. Optional: say "trades with [b]" explicitly in the attack facts instead of implying it. | reported |
| 2026-11-06 | `2026-11-06/287c5bbb-35ed-4ffa-999f-434a8dec33b6` (Claude 3 WR) | 14 | Slayer's trigger made Irreverent Gremlin 3/2 first strike (Claude's reason: so a Beastie+Zealot double block loses the Beastie). Jeff double-blocked with Overgrown Zealot 0/4 + Patchwork Beastie 3/3; all 3 first-strike damage went to the Zealot, Beastie survived and killed the Gremlin. Claude was never asked: the live server (code d4b57ac) predates the DAMAGE decision, so XMage's ComputerPlayer default split it (lethal to each blocker in order, Zealot first). | harness gap (damage among blockers not asked) | DAMAGE decision in PySeat (354d8c9, 2026-11-03): one decision per blocker. Needs a Playmat rebuild + server restart, plus a Claude-service restart for the prompt text. | built, not deployed |
