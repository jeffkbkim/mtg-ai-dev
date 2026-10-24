# Playmat with our players

[Playmat](https://github.com/arcanite24/playmat) is a fan-made web client for XMage, styled after MTG Arena, on an
XMage 1.4.62 fork (the same version as `engine/xmage`). This folder runs it on the Mac mini with our Claude player
as an opponent, and records every game in our decision format. Chosen on 2026-10-23 from a Reddit and GitHub survey
of XMage web clients (Playmat had the best reports and the only working booster draft with AI seats).

Our changes live here, not in a Playmat fork: a patch series against one pinned Playmat commit (`PLAYMAT_COMMIT`),
our Java seat classes, and the scripts that build and run it.

## Play

```sh
engine/playmat/apply_and_build.sh   # once, and after changing anything here (resets ~/dev/playmat to the pin)
engine/playmat/run.sh               # starts it in the background; run.sh stop stops it
```

Then open `http://Bobs-Mac-mini.local:17170` (or `http://<the mini's LAN address>:17170`) from any computer on the
home network, sign in with any name, and on Home open the AI settings (the opponent line under Play):

| AI type | Who plays |
|---|---|
| Playmat AI | you against XMage's standard AI ("Computer - mad") |
| Claude AI | you against our Claude player (`play/players.py`, facts and self-check on; model Opus 5.5 or Sonnet 5.5 and effort low/medium/high in the same dialog, default Opus high) |
| Claude vs Playmat AI | Claude plays your selected deck against XMage's AI; you watch |

Pick a deck. Our starters are real 17lands DSK decks, two colors with at most a light splash: the reviewed good pool
(`engine/xmage/decks/17lands-good`), named with tier, archetype and review rating, e.g. "★★ good_08 · WU eerie
enchantments/tempo · review 4/5", then the older `typical_NN` / `trophy_NN` decks (`engine/xmage/decks/17lands-r2`).
"Good only" (Home, Decks; on by default) shows only the starred decks. The Claude AI is dealt a random good deck, whatever the Rules setting; the other AIs any DSK starter;
choosing the AI's deck in the settings overrides both. Claude always plays first (`PLAY_DRAW=rule`, the default, recorded
as `"source": "rule"`; `PLAY_DRAW=claude engine/playmat/run.sh` lets the model choose).
Claude takes a while per decision (tens of seconds, longer when it self-checks) and costs about $5 a game
(API-equivalent; on a subscription it counts against plan usage).

## Recordings

Each game gets `~/mtg-data/playmat-games/<date>/<game id>/` (`java/GameRecorder.java`), laid out like a
`play/match.py` run so `play/review.py`, `play/summarize.py` and `engine/encode.py` read it:

- `game0.jsonl`: every recorded decision of both seats, in time order. Each line is a PySeat decision (observation
  from that seat's own view, options with ability and choice keys, `leaks` from Observer's checks) plus the pick:
  - Claude: as in match.py runs (prompt, reply, reason, tokens, cost), `"source": "claude"`.
  - Claude lines also carry `model` and `effort`; the first one of a game carries `prewarm` (the process was started
    and the system prompt cached when the game was dealt).
  - You: `"source": "human_ui"`, with `"mapping"` saying how your browser answer was matched to an option: `exact`
    (a priority action, yes/no, a mode, one target), `inferred` (several targets, attackers or blockers, rebuilt as
    PySeat's one-at-a-time sequence from what you declared) or `unmapped` (choice -1, the answer kept in `ui`).
    Blocks XMage refused (a "must be blocked if able" attacker left unblocked) are BLOCK lines with choice -1 and
    `"mapping": "refused"` (what was declared in `ui.declared`): leave them out of training. The accepted blocks follow
    as the usual sequence, from what XMage holds once it accepts them, with `block_attempts` and, if the engine
    changed them, `engine_adjusted: true` and `declared`.
    Priority windows Playmat passed for you (auto-pass, stops) are PASS lines with `"auto": "ui_skip"`. Mana you tap
    by hand is counted in `ui.manual_mana`: it is not a decision our seat has (it pays automatically).
  - Playmat AI: `"source": "xmage_ai"`, `"reconstructed": true`, `"clairvoyant": true`. XMage's AI searches copies of
    the whole game, hidden cards included, so these lines are for reviewing what it did, not imitation labels.
- `seat-A.jsonl`, `seat-B.jsonl`: the same decisions per seat, written as they happened.
- `games.jsonl`: winner, turns, who started, lives, players, decks. `config.json`: seats, deck files, Playmat and
  mtg-ai commits. `deck-A.dck`, `deck-B.dck`: each seat's 40 cards. `game_log.jsonl`: the game log every player sees.
- `errors.log` (Claude seats only, when it happens): a decision flagged as leaking (never shown to the model; option
  0 played, `"leak_blocked": true`) or a model failure after its retries (option 0, `"service_error": true`).

Each game of a best-of-three gets its own folder. Playmat also keeps its own replays (`~/playmat-run/data/server/saved`).

## What is where

- `patches/0001`: the `COMPUTER_CLAUDE` player type ("Computer - claude").
- `patches/0002`: the launcher passes `$PLAYMAT_SERVER_OPTS` to the game server (our `-Dmtgai.*` settings).
- `patches/0003`: the web client's AI types (Playmat AI, Claude AI, Claude vs Playmat AI) and the watch flow, and
  the AI is dealt a `dsk-*` starter deck when the server has them.
- `patches/0004`: the match screen: opponent cards revealed from hand stay shown in their hand until they leave it;
  Rooms preview in landscape and show which door is unlocked.
- `patches/0005`: the deck builder: "DSK only" card filter, the deck by mana value (also read-only for starters on the
  Decks screen), and "Good only" for the starter lists.
- `patches/0006`: the Claude AI's model and effort in the AI settings (sent as the seat's skill: model index * 3 +
  effort index + 1), and its random deck from the good pool.
- `patches/0008`: against any AI the player's opponent gets a DSK deck of about the player's deck's strength (the
  same ★ tier and review rating, then the same rating, then one away; another color pair when possible); a deck the
  player built counts as review 3/5. The AI's deck name says how it was matched and goes to config.json (`deck_name`).
  Watching (Claude vs Playmat AI) stays random.
- `patches/0007`: blocks: attackers that must be blocked if able are marked, blocks that leave one unblocked are held
  back once with a message, and the server's messages to the player (why a block was refused) are shown.
- Our two XMage rule fixes (`engine/xmage/BecomesFaceDownCreatureEffect.java`, `VeteranSurvivor.java`) are copied over
  Playmat's sources at build time, so games here follow the rules our recorded games do.
- `java/ClaudeSeat.java`: PySeat for a Playmat table; connects to `claude_service.py` (port 17180), which runs one
  ClaudePlayer per seat. A Claude seat can't be seated when the service is down (the table says so).
- `java/RecordedHuman.java`, `java/RecordedMad.java`: Playmat's human seat and standard AI, unchanged in play, with
  their decisions recorded through `java/Shadow.java` (PySeat's options, built before the decision).
- `java/GameRecorder.java`: the game folder, decks, game log, result and the merge into `game0.jsonl`.
- `dsk_starters.py`: our DSK decks as Playmat starter decks.
- `run.sh`: Playmat's desktop launcher, headless (server, web client on 17170, its own data in `~/playmat-run/data`,
  accounts off), and the Claude service, both in the background.

## Updating

A daily task reviews Playmat's new commits and moves the pin when it is safe (`UPDATE.md`, `update_upstream.sh`,
`deploy_next.sh`, `test_server.sh`, `smoke.js`; reviews in `upstream-log.md`).

## Known gaps

- The watch mode needs the game to start before it can be watched; if Playmat can't open it, find it under Tables.
- Your mapped decisions are only as exact as the `mapping` field says. Sequences (targets, attackers, blockers) are
  rebuilt in the order XMage holds them, not the order you clicked, and every step carries the observation from
  before your first click.
- XMage's AI records are rebuilt from what it did; a priority call where it did several things is split into one
  priority decision per action, each with the options at that moment.
- Draft with our AI and the Special Guests in DSK boosters are not done.
