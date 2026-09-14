# Working on Splice

- **One worktree per agent, never the root checkout.** Set up with
  `scripts/agent-worktree.sh <role>`; work on `agent/<role>`; ship with
  `scripts/ship.sh`. Roles and rules: `docs/AGENTS.md`.
- **Every change goes to both repositories** (origin and the Versigent
  mirror). `scripts/ship.sh` does it; do not push by hand.
- **Read the suite's exit code, never its tail.** `pytest | tail` hides a
  failure; the ship script captures the code.
- **Engines stay output-identical** unless the change is the point: prove
  workbook changes with a cell diff; keep the page tests green.
- Design: `docs/NICEGUI_DESIGN.md` (tokens, archetypes, canon, review gates).
