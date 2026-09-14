#!/usr/bin/env bash
# One git worktree per agent, so no two sessions ever share a working tree.
#
#   scripts/agent-worktree.sh <role>      e.g. ui-ux, software-engineer
#
# Creates ../<repo>-wt/<role> on branch agent/<role> cut from origin/main
# (or attaches to the branch if it already exists), copies the untracked
# .claude/launch.json so the preview server works there, and proves that
# Python imports resolve to the worktree and not to the root checkout.
set -euo pipefail

ROLE=${1:?usage: scripts/agent-worktree.sh <role>   (lowercase, digits, dashes)}
[[ "$ROLE" =~ ^[a-z0-9-]+$ ]] || { echo "role must be lowercase letters, digits and dashes"; exit 1; }

COMMON=$(git rev-parse --path-format=absolute --git-common-dir)
MAIN_ROOT=$(dirname "$COMMON")
WT_DIR="$(dirname "$MAIN_ROOT")/$(basename "$MAIN_ROOT")-wt"
WT="$WT_DIR/$ROLE"
BRANCH="agent/$ROLE"
PY=${PYTHON:-python}

mkdir -p "$WT_DIR"
git fetch -q origin
if [ -d "$WT" ]; then
  echo "worktree already exists: $WT"
elif git show-ref --quiet "refs/heads/$BRANCH"; then
  git worktree add "$WT" "$BRANCH"
else
  git worktree add -b "$BRANCH" "$WT" origin/main
fi
[ -f "$MAIN_ROOT/.claude/launch.json" ] && [ ! -f "$WT/.claude/launch.json" ] \
  && mkdir -p "$WT/.claude" && cp "$MAIN_ROOT/.claude/launch.json" "$WT/.claude/launch.json"

( cd "$WT" && "$PY" - "$WT" <<'PYEOF'
import sys, splice, nicegui_app
wt = sys.argv[1]
for mod in (splice, nicegui_app):
    assert mod.__file__.startswith(wt), f"{mod.__name__} imports from {mod.__file__}, not this worktree"
print("imports resolve to this worktree")
PYEOF
)
echo "ready: $WT  (branch $BRANCH)"
echo "next: open your Claude Code session ON this path (a mid-session cd does not re-target the preview server), work, then scripts/ship.sh"
