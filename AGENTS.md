# Instructions for AI coding agents

This file guides AI coding agents (Claude Code, Codex) working in this repository. The owner designs and writes the
model, loss and training code; agents build infrastructure under the owner's direction. Long jobs run on an M4 Mac mini
with 16 GB unified memory; GPU rental may be used later.

## Ownership

- For model representation, architecture, forward pass, loss and training-loop work, default to hints, explanations and review. Do not implement those parts unless the user asks.
- For research, setup, data download/parsing, integration and routine infrastructure, implement directly when requested.
- The user drives model design. Do not write design docs, diagrams, proposed architectures or option tables for the model unless explicitly asked; answer the question asked and let the user make each decision.
- Explain design tradeoffs in plain language. Treat architecture choices as hypotheses, not established winners.

## Scope and correctness

- First format: DSK Limited. Gameplay before drafting, direct policy before optional search.
- Reuse a rules engine. XMage is tentative, not a verified integration decision.
- Do not expose opponent hidden cards, hidden face-down identities, or future draws. Preserve information legitimately revealed to the acting seat.
- Never silently replace unsupported cards in training or evaluation.
- Keep whole games and drafts together across train/validation/test; paired recordings must share a split.
- Human move agreement is not proof of playing strength. Evaluate actual games with fixed opponents, seat balance and uncertainty intervals.
- Record exact versus inferred reconstruction and surface known failures.

## Project hygiene

Keep large data, checkpoints and secrets outside Git. Record experiment configuration, dataset version, seed and code commit. Update docs/plan.md and docs/decisions.md when material decisions change. Use separate branches for concurrent tasks.

## Mac mini heavy jobs

The mini has 16 GB. On 2026-10-28 four 17lands turn-replay processes reached ~13 GB each while loading the replay data, and WindowServer hung, which logged the user out.
- Replay search (seventeenlands turn_replay): fixed 2026-10-29. Picking the sample games decodes whole row groups of the
  1M-game parquet (~7-8 GB for a few seconds); it now runs in a short-lived child process, one worker at a time
  (a lock), so each worker then holds only ~100 MB of Python plus its JVM (-Xmx4g). Measure before going above 3 workers. Agents don't start replay search on their own.
- Never run heavy jobs alongside each other: the nightly soak, builds, test servers, the decisions export, replay search.
- The user is fine with heavy jobs while they play Playmat games (2026-10-29).
- Guard long data jobs on the process's own memory (RSS/footprint) as well as on swap and free memory, and stop them before the box swaps hard.

## Corrections (mistakes not to repeat)

- Check where an observation field is actually filled before relying on it. Card `keywords` are listed only for
  battlefield permanents, not for cards in hand, so flash must come from the card's rules text (2026-11-05).
