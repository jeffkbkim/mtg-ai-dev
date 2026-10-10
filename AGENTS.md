# Collaboration instructions

The user is a beginner learning Python and ML, with an M4 Mac mini and 16 GB unified memory. GPU rental may be used later.

## Learning ownership

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
