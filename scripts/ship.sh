#!/usr/bin/env bash
# Ship the current agent branch: rebase onto origin/main, run the suite and
# read its exit code, push the branch, fast-forward main, mirror to versigent.
#
#   scripts/ship.sh            from inside your worktree, on agent/<role>
#
# Nothing here forces anything. If origin/main moved under you, the rebase
# stops and you resolve; if someone landed first while the suite ran, the
# push of main is refused as non-fast-forward and you re-run. Local `main`
# is never touched (it is checked out in the root); remotes are updated
# directly from the agent branch.
set -euo pipefail

BRANCH=$(git branch --show-current)
case "$BRANCH" in agent/*) ;; *) echo "ship.sh runs on an agent/<role> branch — you are on '$BRANCH'"; exit 1 ;; esac
if [ -n "$(git status --porcelain)" ]; then echo "commit or discard first:"; git status --short; exit 1; fi

PY=${PYTHON:-python}
PERSONAL=${GH_PERSONAL:-Jaramillo35}
WORK=${GH_WORK:-Jaramillo35Versigent}

echo "== rebase onto origin/main"
git fetch -q origin
git rebase -q origin/main || { echo "rebase stopped — resolve it, then re-run"; exit 1; }

echo "== suite"
LOG=$(mktemp -t ship-suite.XXXX)
set +e; "$PY" -m pytest -q -p no:warnings > "$LOG" 2>&1; RC=$?; set -e
tail -1 "$LOG"
[ "$RC" -eq 0 ] || { echo "suite exit $RC — not shipping (log: $LOG)"; exit "$RC"; }

echo "== origin"
git push origin "$BRANCH"
git push origin "$BRANCH:main"

echo "== versigent"
BEFORE=$(gh api user -q .login 2>/dev/null || echo "$PERSONAL")
restore() { gh auth switch -u "$BEFORE" >/dev/null 2>&1 || true; }
trap restore EXIT
gh auth switch -u "$WORK" >/dev/null
git fetch -q versigent main
if git merge-base --is-ancestor versigent/main "$BRANCH"; then
  git push versigent "$BRANCH:main" "$BRANCH:$BRANCH"
else
  echo "versigent/main holds a commit this branch does not — not pushing there; ask before forcing"
  exit 2
fi
restore; trap - EXIT
git fetch -q origin
echo "shipped $(git rev-parse --short HEAD): origin/main=$(git rev-parse --short origin/main) versigent/main=$(git rev-parse --short versigent/main 2>/dev/null || echo '?') gh=$(gh api user -q .login 2>/dev/null)"
