# Playmat upstream log

Newest first. Written by the daily review (UPDATE.md).

## 2026-11-14 (daily review) — HELD
- PRs (check_upstream_prs.sh): no PR changes. #105-#112 MERGED; #113 OPEN, CONFLICTING, CI failing, 1 comment from
  arcanite24 (the 2026-11-03 "debug duck" note, still unanswered, waits for Jeff).
- a33fb65 → 629e3175 (Playmat master, 2026-11-14): 1399 commits, 457 new since the last reviewed 59de56f (383
  non-merge; no 11-13 entry). The new ones: mostly Rust engine waves 6-7 (per-card handlers, transpiler forms, cost
  adjusters, bestow/reconfigure/craft/station/escalate etc., shadow games, ~11,129 cards verified, phase 4 gate 9,949
  of 10,000); server: shared decks (#137), player directory, appear offline, Discord join posts, account-search LIKE
  escape; web client: Arena-style pass-turn button, deck covers/tags/filters (#167/#200), "only these colors" filter
  (#198), notification kinds and table-join alerts. Mage/src/main since 59de56f: GameImpl (+3), trace DecisionLog and
  RustAiBridge (logging; no rules behaviour seen). Security: Mage.Server/pom.xml only adds three classes to a list (no
  new dependency); backup.sh adds web_presence.db; DiscordNotifier gains table-join posts (off unless
  xmage.discordWebhook is set); no new outbound hosts beyond github.com links.
- Gate: HOLD, same open reasons as 2026-11-07..12 across the whole range: rules changes under Mage/src/main (incl.
  the #255 rules batch and the getPlayable pay-mana change); DSK cards RootwiseSurvivor and VeteranSurvivor changed;
  patch 0003 conflicts (i18n en/core.ts, es.ts, stores/play.ts), 0004-0037 unchecked; security pass not cleared for
  the whole range (TrustedHeaderAuth, OIDC sign-in, deck-import fetches, Docker/Caddy/updater, CI). Needs Jeff to plan
  the rebase.
- No build, no tests, not deployed. Pin stays a33fb65.

## 2026-11-12 (daily review) — HELD
- PRs (check_upstream_prs.sh): no PR changes. #105-#112 MERGED; #113 OPEN, CONFLICTING, CI failing, 1 comment from
  arcanite24 (the 2026-11-03 "debug duck" note, still unanswered, waits for Jeff).
- a33fb65 → 59de56f (Playmat master, 2026-11-11): 942 commits, 46 new since yesterday's eb69627 (29 non-merge). The
  new ones: Rust engine shadow fixes (cleanup with SBAs asks priority, Roles leaving a noncreature, Valgavoth, tap
  costs, damage replacement order, Giada, combat damage step powers, ward/valiant waiting on triggers, kicker
  counters, Room triggers keeping their face, Lessons); Rust host games between people (#189), Career payouts and
  economy calls in Rust (XMAGE_ROUTE_CAREERPAYOUTS), Rust AI policy interface/MCTS/Archbench (PLAYMAT_AI_POLICY),
  phase 4 gate numbers and 10,000 shadow games; gateway counters that survive deploys (GET /totals, their gateway
  port 17180 — same number as our Claude service, only matters if we ever run their gateway); web client: cached card
  pictures show on the first frame (#288), hand discards on Rust, first strike lunges once (#291); docs/gitignore/CI
  clippy fixes. Mage/src/main today: PreparedSpellCopy getter, GameOptions.hostedLine, trace DecisionLog/ShadowStart
  (no rules behaviour). Security: new Rust dependency sha2 0.10 (playmat-platform), entrypoint/compose payout and
  gateway-totals settings; no new outbound URLs today.
- Gate: HOLD, same open reasons as 2026-11-07..11 across the whole range: rules changes under Mage/src/main (incl.
  the #255 rules batch and 11-11's getPlayable pay-mana change); DSK cards RootwiseSurvivor and VeteranSurvivor
  changed; patch 0003 conflicts (stores/play.ts), 0004-0037 unchecked; security pass not cleared (TrustedHeaderAuth,
  OIDC sign-in and its server dependency, deck-import fetches, Docker/Caddy/updater, CI changes). Needs Jeff to plan
  the rebase.
- No build, no tests, not deployed. Pin stays a33fb65.

## 2026-11-11 (daily review) — HELD
- PRs (check_upstream_prs.sh): no PR changes. #105-#112 MERGED; #113 OPEN, CONFLICTING, CI failing, 1 comment from
  arcanite24 (the 2026-11-03 "debug duck" note, still unanswered, waits for Jeff).
- a33fb65 → eb69627 (Playmat master, 2026-11-10): 896 commits, 54 new since yesterday's 00c2043 (36 non-merge). The
  new ones: Rust engine parity (poison/704.5c, granted deathtouch/defender in combat, 514.3a cleanup priority,
  delve/convoke/improvise while paying, effect-added subtypes, infinite-loop draw, looked-at cards, library search
  view); Rust host (spectators/chat/emotes, undo tap and rollbacks, mana payment modes, hold priority, replays, Career
  payouts, printings, leyline in opening hand, view templates); Rust engine opt-in setting (UserData.useRustEngine,
  XMAGE_RUST_OPT_IN, chip on the board); web client warms card pictures before a match, deck-builder binder tiles fix
  (#277/#279); CI pre-push ops/ci/check.sh and faster workflows. Mage/src/main today: PlayerImpl.getPlayable no longer
  skips while in pay-mana mode (mana sources for costs paid while attacking, e.g. Propaganda), UserData opt-in field,
  trace/ShadowStart.java. Security: new Rust dependency flate2 (playmat-host, replay compression), CI workflow edits,
  entrypoint opt-in switch; no new outbound URLs today.
- Gate: HOLD, same open reasons as 2026-11-07..10 across the whole range: rules changes under Mage/src/main (incl.
  the #255 rules batch, and today's getPlayable change in pay-mana mode); DSK cards RootwiseSurvivor and
  VeteranSurvivor changed; patch 0003 conflicts (stores/play.ts), 0004-0033 unchecked; security pass not cleared
  (TrustedHeaderAuth, OIDC sign-in and its server dependency, deck-import fetches, Docker/Caddy/updater, CI changes).
  Needs Jeff to plan the rebase.
- No build, no tests, not deployed. Pin stays a33fb65.

## 2026-11-10 (daily review) — HELD
- PRs (check_upstream_prs.sh): no PR changes. #105-#112 MERGED; #113 OPEN, CONFLICTING, CI failing, 1 comment from
  arcanite24 (the 2026-11-03 "debug duck" note, still unanswered, waits for Jeff).
- a33fb65 → 00c2043 (Playmat master, 2026-11-09): 842 commits, 14 new since yesterday's fb45469. The new ones: Rust
  game host rollout step E (hosted-game metrics, XMAGE_RUST_HOST_USERS), priority timers, best-of-three matches,
  per-game records + host-replay (gateway/host, RustHost.java, GameApi), Modern tier34 meta decks and transpiled
  cards (rust engine rules.rs/state.rs/card.rs), "skip empty target prompts" (#265: HumanPlayer.chooseTarget returns
  early when nothing is choosable; RelicOfProgenitus checks canChoose; no DSK card), web client headless bot/Rust host
  live tests; ops: .env.example/docker-compose/server-entrypoint.sh add XMAGE_RUST_HOST_RECORDS(_KEEP), local paths
  only, no new URLs or dependencies today.
- Gate: HOLD, same open reasons as 2026-11-07..09 across the whole range: rules changes under Mage/src/main (incl.
  the #255 rules batch); DSK cards RootwiseSurvivor and VeteranSurvivor changed; patch 0003 conflicts
  (stores/play.ts), 0004-0033 unchecked; security pass not cleared (TrustedHeaderAuth, OIDC sign-in and its new
  server dependency, deck-import fetches, Docker/Caddy/updater). Today's commits add nothing new to clear or block.
  Needs Jeff to plan the rebase.
- No build, no tests, not deployed. Pin stays a33fb65.

## 2026-11-09 (daily review) — HELD
- PRs (check_upstream_prs.sh): no PR changes. #105-#112 MERGED; #113 OPEN, CONFLICTING, CI failing, 1 comment from
  arcanite24 (the 2026-11-03 "debug duck" note, still unanswered, waits for Jeff).
- a33fb65 → fb45469 (Playmat master, 2026-11-08): 828 commits, 85 new since yesterday's 690a718. The new ones: Rust
  views vs Java (Views: stack, combat, exile, rooms, tokens...), Rust game host step D (AI duels on the Rust engine
  through the gateway), Rust meta decks and tracker; OIDC sign-in (#215) and GitHub/OIDC sign-in hardening (account
  takeover by email, login CSRF, state replay; #252); phone layouts (#247); web client match size/zoom keys, revealed
  cards kept for the turn, deck-builder magnifier, gauntlet fixes; AI batch (never counter own spells, no attacks with
  fully prevented damage, per-turn action cap); rules batch (#255) touching Mage/src/main ContinuousEffects,
  PreventionEffectImpl and several common effects; server lists mana sources when paying without priority;
  Mage.Server/pom.xml +8 (OIDC dependency).
- Gate: HOLD, same open reasons as 2026-11-07/08 plus today's rules batch under Mage/src/main (continuous and
  prevention effects); DSK cards RootwiseSurvivor and VeteranSurvivor changed in range; patch 0003 conflicts
  (stores/play.ts), 0004-0033 unchecked; security pass not cleared (now also OIDC/auth code and a new server
  dependency, on top of TrustedHeaderAuth, deck-import fetches, Docker/Caddy/updater). Needs Jeff to plan the rebase.
- No build, no tests, not deployed. Pin stays a33fb65.

## 2026-11-08 (daily review) — HELD
- PRs (check_upstream_prs.sh): no PR changes. #105-#112 MERGED; #113 OPEN, CONFLICTING, CI failing, 1 comment from
  arcanite24 (the 2026-11-03 "debug duck" note, still unanswered, waits for Jeff).
- a33fb65 → 690a718 (Playmat master, 2026-11-07): 743 commits, 14 new since yesterday's dd3e223. The new ones: Rust
  AI (diverge logging, mana color questions, parallel test games, per-game CPU cost), Rust engine tier31 meta decks,
  GameHost/Ai plans and docs, signature spell VFX and token art (web client, #226), a public Rust-port tracker site
  (site/rust, .github/workflows/site.yml), server support/PlayerLook and RustAi tweaks, Mage/ game/trace
  GameTrace and RustAiBridge (tracing, not rules).
- Gate: HOLD, same reasons as 2026-11-07, all still open: rules changes under Mage/src/main across the whole range;
  DSK cards RootwiseSurvivor and VeteranSurvivor changed; patch 0003 conflicts (stores/play.ts), 0004-0033
  unchecked, and several likely duplicate merged #105-#112; security pass not cleared (TrustedHeaderAuth, outbound
  deck-import fetches to archidekt/mtgtop8/tcgplayer/manabox, Docker/Caddy/entrypoint/updater, plus a new CI
  workflow for the site today). Needs Jeff to plan the rebase onto the new upstream.
- No build, no tests, not deployed. Pin stays a33fb65.

## 2026-11-07 (daily review) — HELD
- PRs (check_upstream_prs.sh): #105-#112 MERGED upstream (dim tapped/open lands, extra origins, deck columns,
  combat estimate, must-be-blocked warning, trigger signal, keyword help/counters, revealed hand/Rooms).
  #113 (library list, mana available, AI thinking timer) OPEN, now CONFLICTING, CI failing (build jdk17, check);
  1 comment from arcanite24 (2026-11-03): thanks for the PRs, contributors get a "debug duck" pet, asks for the
  account name on playmat.deimos.studio to add it. No reply sent (waits for Jeff).
- a33fb65 → dd3e223 (Playmat master, 2026-11-06): 729 commits, too many for one line each; areas: a new Rust engine
  and Rust AI (rust/, shadow replays vs Java, ~27% of files), cards (392 card files, many XMage upstream fixes),
  rules engine Mage/src/main (103 Java files, 97 commits: GameImpl, GameState, ZonesHandler, Exile, targets and
  target pointers, Spell, PermanentImpl, NumberOfTriggersEvent, ZoneChangeGroupEvent removed, draft pick suggest,
  DecisionLog/RustAiBridge traces, set ratings), XMage AI (ComputerPlayer -232 lines, ComputerPlayer6, RustHumanPlayer),
  server (websocket APIs, TrustedHeaderAuth, accounts, support), web client (178 files, incl. our merged PRs),
  launcher (Network.java), ops/web (Docker, Caddy, entrypoint, updater).
- Gate: HOLD. (1) Rules-relevant changes under Mage/src/main (zones, exile, targets, triggers, game state).
  (2) Two DSK cards we play changed: RootwiseSurvivor (75f4f1ae3d: becomes-creature keeps prior types) and
  VeteranSurvivor (34ef616cd4, fix #16482: exile zone id by zone change counter); both look like fixes but change
  rules behaviour. (3) Patch series: 0001-0002 apply, 0003 conflicts (stores/play.ts), 0004-0032 unchecked; with
  #105-#112 merged upstream several patches likely duplicate upstream code and need Jeff to decide what to drop.
  (4) Security pass not cleared: new TrustedHeaderAuth (login via proxy header), new outbound deck-import fetches
  (rust playmat-platform deckimport: archidekt, mtgtop8, tcgplayer, manabox), Docker/Caddy/entrypoint/updater changes,
  new AI module dependency (mage-player-human, provided). Need a proper read before moving the pin.
- Also: update_upstream.sh died with SIGPIPE (exit 141) on `git log | head -60` under pipefail with >60 commits;
  changed to `sed -n '1,60p'`.
- No build, no tests, not deployed. Pin stays a33fb65.

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
