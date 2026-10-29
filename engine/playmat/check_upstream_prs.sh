#!/usr/bin/env bash
# Our upstream PRs to Playmat (arcanite24/playmat #105-#113, from kimbobmarley03): state, mergeability, CI, reviews and
# comments, read-only. Compares with the last snapshot (upstream-prs.json, committed) and prints one line per PR, then
# CHANGED lines for anything new since the snapshot (merged, closed, a review or comment, a new conflict, CI failing),
# or "no PR changes". Updates the snapshot. Never comments, pushes or rebases.
#
#   engine/playmat/check_upstream_prs.sh            # PRS="105 106 ..." to check others
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
SNAP=$HERE/upstream-prs.json
PRS=${PRS:-"105 106 107 108 109 110 111 112 113"}
NOW=$(mktemp)
trap 'rm -f "$NOW"' EXIT
echo '{' > "$NOW"
first=1
for n in $PRS; do
  json=$(gh pr view "$n" -R arcanite24/playmat --json number,title,state,mergeable,mergedAt,closedAt,reviews,comments,statusCheckRollup \
    --jq '{state, mergeable, mergedAt, closedAt, title: .title[0:70],
           reviews: (.reviews | length), comments: (.comments | length),
           lastActivity: ([.reviews[].submittedAt, .comments[].createdAt] | max),
           others: ([.reviews[].author.login, .comments[].author.login] | map(select(. != "kimbobmarley03")) | unique),
           checks: ([.statusCheckRollup[]? | (.conclusion // .status)] | unique)}')
  [ $first = 1 ] || echo ',' >> "$NOW"
  first=0
  printf '"%s": %s\n' "$n" "$json" >> "$NOW"
done
echo '}' >> "$NOW"
python3 - "$SNAP" "$NOW" <<'PY'
import json, sys
old = json.load(open(sys.argv[1])) if __import__("os").path.exists(sys.argv[1]) else {}
new = json.load(open(sys.argv[2]))
changes = []
for n, pr in new.items():
    print(f"#{n} {pr['state']} {pr['mergeable']} checks={','.join(pr['checks']) or '-'} reviews={pr['reviews']} comments={pr['comments']}"
          + (f" from {','.join(pr['others'])}" if pr['others'] else "") + f" | {pr['title']}")
    was = old.get(n)
    if was is None:
        continue
    for key in ("state", "mergeable", "reviews", "comments", "checks"):
        if pr[key] != was.get(key):
            changes.append(f"CHANGED #{n} {key}: {was.get(key)} -> {pr[key]}")
    if any(c not in ("SUCCESS", "SKIPPED", "NEUTRAL") for c in pr["checks"]) and pr["checks"] != was.get("checks"):
        changes.append(f"CHANGED #{n} CI not passing: {pr['checks']}")
print("\n".join(changes) if changes else "no PR changes")
json.dump(new, open(sys.argv[1], "w"), indent=1, sort_keys=True)
PY
