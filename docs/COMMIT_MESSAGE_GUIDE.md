# Commit Message Guide

## Why

Short messages like "push" and "fix" hide intent and slow reviews. Use clear, scoped messages that explain business value or risk.

## Recommended format

```text
<type>(<scope>): <imperative summary>
```

Types:
- feat: new behavior
- fix: bug fix
- refactor: internal change, no behavior change
- docs: documentation
- test: test-only change
- ci: workflow/pipeline change
- chore: maintenance

## Good examples

- feat(splice): add endpoint-level sales code simplification toggle
- fix(dtx): handle missing connector columns with explicit validation error
- docs(readme): add architecture and measurable impact section
- ci(tests): run pytest on push and pull request
- test(preorder): skip fixture-dependent test when sample files are unavailable

## Anti-patterns

- push
- fix
- updates
- misc changes

## Optional body template

```text
Problem:
- what failed or was unclear

Solution:
- what changed

Validation:
- tests or manual checks performed
```
