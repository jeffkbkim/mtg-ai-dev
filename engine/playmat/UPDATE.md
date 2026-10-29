# Keeping up with Playmat

Playmat (github.com/arcanite24/playmat) changes most days. We run one pinned commit (`PLAYMAT_COMMIT`) with our patch
series; a daily task (the Claude app's scheduled task "Playmat upstream review", 5:00 AM) moves the pin forward when
that is safe, and holds it for Jeff when it isn't. Each run appends its review to `upstream-log.md`.

## Steps

0. Every run, before anything else: `engine/playmat/check_upstream_prs.sh` checks our upstream PRs (#105-#113,
   read-only) against the last snapshot (`upstream-prs.json`). Put its lines in the run's log entry. Any CHANGED line
   (merged, closed, a maintainer review or comment, a new conflict, CI not passing) goes first in the run's final
   message, with the comment text summarised, so it reaches Jeff. Never comment, push, rebase or force-push on
   Playmat's GitHub: a reply or a rebase (e.g. #108's conflict) waits for Jeff's yes.
1. `engine/playmat/update_upstream.sh` fetches Playmat's master and prints the new commits, files changed per area,
   which DSK card files changed, the security pass inputs (dependency, build, install and CI changes; URLs the new
   code adds) and whether our patches still apply. No new commits: log "no changes" and stop.
2. Review each new commit in one line: what it does and its area (web client, bridge/server, rules engine `Mage/`,
   XMage AI, cards, launcher/ops). Security pass on the diff: new network endpoints or outbound calls, credential or
   session handling, install/build scripts, new or changed dependencies (package.json, pom.xml), CI workflows.
3. Gate. Hold (don't move the pin) and report when:
   - anything under `Mage/src/main` changes rules behaviour (effects, combat, layers, triggers, costs, mana, targets,
     state-based actions, zones), or any DSK/SPG card file or the DSK/SPG set files change. Pure additions that
     nothing in a DSK game calls (a new option, a puzzle mode, logging) and performance rewrites that keep results
     are fine but say so in the log;
   - the security pass finds anything we can't explain;
   - a patch can't be carried over without guessing what the new upstream code means.
4. Otherwise update:
   - Carry the patch series over: in a scratch worktree at the new commit, apply `patches/*.patch` in order; for a
     conflict, redo our change by hand on the new code (keep the `mtg-ai:` comments), then regenerate that patch
     with `git diff` against the state before it, so the series applies in order on the new pin. Our Java and
     Python don't depend on Playmat's commit and need no change unless the build says so.
   - Set `PLAYMAT_COMMIT` to the new commit and build: `OUT=~/playmat-run/build-next engine/playmat/apply_and_build.sh`.
   - Test, never on the live server: `npx vitest run` and `npx tsc -b` in `~/dev/playmat/Mage.Web.Client` (a test
     that failed before the update may still fail; say which); our engine checks (engine/xmage/README.md, "Checks");
     then `engine/playmat/test_server.sh`, Vite on 4180 against it (see that script), and
     `NODE_PATH=$(npm root -g) node engine/playmat/smoke.js claude "Sonnet 5.5" Low` for about 30 seconds: a table
     against the Claude AI must seat and Claude must answer its first decision (check the newest folder under
     `~/playmat-run/test/rec`). Stop the smoke, Vite and `test_server.sh stop` afterwards.
   - Commit to main (patches, `PLAYMAT_COMMIT`, `upstream-log.md`) and push. Do NOT deploy: a person deploys with
     `engine/playmat/deploy_next.sh --go` after checking nobody is playing (since 2026-10-24, when a deploy killed a
     live game). Leave the build in `~/playmat-run/build-next` and say it is ready.
5. Log the run at the top of `upstream-log.md`: date, old and new commit, the commit list with areas, the gate result
   and why, test results, deployed or not. Commit and push it even when holding.

Rollback: `engine/playmat/run.sh stop`, swap `~/playmat-run/build` and `build-prev`, `engine/playmat/run.sh`, and
set `PLAYMAT_COMMIT` back.
