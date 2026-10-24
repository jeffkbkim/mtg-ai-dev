# Playmat upstream log

Newest first. Written by the daily review (UPDATE.md).

## 2026-10-24 (by hand, Jeff asked)
- 95974c0 → a33fb65 (Playmat master, 2026-10-23), 22 commits: keyboard play shortcuts and choice navigation,
  accidental-keyboard-choice guard, mana choices as symbol buttons (single mana abilities keep their confirmation),
  emoji glyphs replaced by SVG icons, equipped cosmetics for every seat, account confirmation and flag badges,
  format (meta) deck pools validated and expanded with weighted picks, "look at the top card any time" shown on
  the library and castable from there (Realmwalker, Bolas's Citadel).
- Engine: `Mage/` adds `Player.isTopCardVisibleToSelf()` set by LookAtTopCardOfLibraryAnyTimeEffect, and PlayerView
  shows the top card only in that player's own view. No rules change; no DSK card uses that effect; Observer doesn't
  read the top card; opponents' views unchanged (no leak). No AI, DSK/SPG card or set file changes. No dependency,
  build, CI or script changes; no new URLs in code.
- Patches carried over: 0003 and 0006 had context conflicts in stores/play.ts (the aiDecks doc comment); merged by
  hand, logic unchanged. All seven regenerated.
- Tests: web client tsc clean, vitest 1230 passed / 12 skipped; build OK; test-server smoke (Claude AI, Sonnet low):
  table seated, Claude answered, 0 leaks, human lines exact, model and effort recorded. Our Java and checks unchanged.
- Deploy: deploy_next.sh, after Jeff's game in progress ends.

## 2026-10-23 (set up)
- Pin 95974c0 (2026-10-21). Playmat master was 22 commits ahead (web client: keyboard play, cosmetics, mana-choice
  symbols, AI deck pool, Realmwalker top card; `Mage/`: a "look at the top card" addition in Player/PlayerImpl and
  LookAtTopCardOfLibraryAnyTimeEffect). No DSK card changes. Patch 0003 conflicts in stores/play.ts. Not updated:
  left for the first scheduled run.
