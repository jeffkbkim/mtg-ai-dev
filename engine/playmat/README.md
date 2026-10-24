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
  mtg-ai commits. `deck-A.dck`, `deck-B.dck`: each seat's 40 cards (counted over every zone at the seat's first
  decision, so a resumed game has all 40 too; a count other than 40, or a deck that differs from the resumed game's,
  is listed in config.json's `warnings`). `game_log.jsonl`: the game log every player sees.
- `errors.log` (Claude seats only, when it happens): a decision flagged as leaking (never shown to the model; option
  0 played, `"leak_blocked": true`) or a model failure after its retries (option 0, `"service_error": true`).

Each game of a best-of-three gets its own folder. Playmat also keeps its own replays (`~/playmat-run/data/server/saved`).

### Take-backs

Playmat lets the player take a turn back in two ways, and both are recorded. Nothing is deleted: what was undone is
marked.

- **Rollback** (XMage's "Player request: Rolling back to start of turn N"): the same game and folder. config.json gets
  `has_rollback: true` and `rollbacks` [{ts, to_turn, from_turn}], the games.jsonl line `rollbacks`. In game0.jsonl
  each decision recorded before the rollback, from turn N on, gets `"superseded": true, "superseded_by": "rollback"`,
  and every decision after the first rollback `"after_rollback": true` (the seat files stay as written). The priority
  window the player asked from is a choice -1 line with `ui.rollback_request`, not a PASS. A Claude seat is told
  (`{"type": "rollback"}`): its conversation restarts, with its log lines from turn N on kept but marked "(undone by
  a rollback)".
- **Resume** (Playmat's take-back / "try this turn again" / a saved game: "The game carries on from the start of
  turn N"): a new game id and folder. Its config.json gets `resumed_from_turn`, `resumed_from` (the earlier game's id:
  the latest recording of the same players that reached turn N and ended at most ten minutes before, or never
  ended), `resumed_from_dir` and `resumed_from_seats` (seat letters can swap between the two). The earlier folder gets
  `superseded_by.json` {game_id, from_turn, ts, dir} (also in its config.json), `"ended_by": "resumed elsewhere"` on its
  games.jsonl line (the winner there is whoever was ahead when the player left, not a real result), and its decisions
  from turn N on are superseded (`"superseded_by": "resume:<new id>"`). A Claude seat in the new game gets the log it
  had in the earlier one(s), rebuilt from their seat files, the part from turn N on marked "(undone by a take-back)".

XMage restores the whole state at the start of turn N, library order and the game's random generator included, so
the same cards are drawn again in the same order. Both players remember what the undone turns showed (the human his
own next draws, any card the opponent cast or revealed; Claude the same from its marked log). Games with a take-back
are not clean evaluation games, and the decisions after one are made with that knowledge: `play/manifest.py` calls a
superseded game "suspect" and gives rollback and resumed games a caution; it, `play/review.py` and
`play/review_turns.py` leave superseded decisions out (summarize.py still counts their cost: it was spent).

`engine/playmat/fix_resumed_recordings.py` applies the same marks to folders recorded before this (dry run by default,
`--apply` to write; each rewritten file is kept once as `.orig`). It also replaces a resumed folder's short deck files
with the earlier recording's 40 cards (the short one kept as `deck-X.partial.dck`).

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
- `patches/0009`: Home lists decks by stars (★★, ★, then the rest; then review rating; saved copies of starters by their
  cards); clicking your own library lists its cards in random order (the server sends name counts only to that player:
  `PlayerView.libraryCards`); "Claude is thinking… Ns" on the AI's plate; "N mana available" on yours; the deck index is
  always refetched.
- `patches/0010`: keyword help: a Mechanics panel beside the hovered card, keywords marked and explained in the card
  detail, DSK glossary entries (Impending, Manifest dread, face-down, Rooms, stun and finality counters), counters as
  symbols and "Impending N" on the board.
- `patches/0011`: combat preview while blocking (and the unblocked damage while attacking): who dies, the life after
  combat, an estimate that ignores tricks and triggers.
- `patches/0012`: a trigger signal: the source of a triggered ability (Eerie and others) glows and shakes for about a
  second, with a label and a short sound (muted with the game sounds).
- `patches/0013`: "Opponent can't win: end game (claim win)" in the game menu against the computer: every computer
  opponent concedes and the result says `"ended_by": "human_claim"`; the AI deck matcher also knows unlisted rated decks
  (`starter-decks/strengths.json`), so an old saved copy still gets a matched opponent.
- `patches/0014`: saved copies of our starters stay in step: on each load an unmodified copy is renamed to the current
  starter name, exact duplicates are merged, copies of retired decks are labelled "Retired" and sorted last (hidden by
  Good only); one sort for saved and starter decks by real strength; tiles say "Your copy · ★★ starter". Decks the
  player renamed, duplicated, imported or built are flagged and never touched.
- `patches/0015`: one shared deck set on the mini for every window: with accounts off, Playmat's deck sync reads and
  writes ~/mtg-data/my-decks/ (`<id>.dck` + `.json`, index.json, manifest.json for play/review_decks.py, backups,
  deleted/ instead of deleting); LAN-only. Decks of 40+ DSK cards form the "DSK Draft (40)" set (a client label and
  filter; the XMage deck type stays Freeform). Ratings written into its manifest.json reach the deck matcher.
- `patches/0016`: tapped permanents are dimmed as well as turned; land piles show open lands first and "N / M open".
- `patches/0017`: the launcher also accepts the origins in `$PLAYMAT_EXTRA_ORIGINS` (run.sh: https://play.devpick.sh, the
  Cloudflare tunnel behind Cloudflare Access).
- `patches/0007`: blocks: attackers that must be blocked if able are marked, blocks that leave one unblocked are held
  back once with a message, and the server's messages to the player (why a block was refused) are shown.
- Our two XMage rule fixes (`engine/xmage/BecomesFaceDownCreatureEffect.java`, `VeteranSurvivor.java`) are copied over
  Playmat's sources at build time, so games here follow the rules our recorded games do.
- `java/ClaudeSeat.java`: PySeat for a Playmat table; connects to `claude_service.py` (port 17180), which runs one
  ClaudePlayer per seat. A Claude seat can't be seated when the service is down (the table says so).
- `java/RecordedHuman.java`, `java/RecordedMad.java`: Playmat's human seat and standard AI, unchanged in play, with
  their decisions recorded through `java/Shadow.java` (PySeat's options, built before the decision).
- `java/GameRecorder.java`: the game folder, decks, game log, result, the merge into `game0.jsonl` and the take-back
  marks; `fix_resumed_recordings.py` does the same for older folders.
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
