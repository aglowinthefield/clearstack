---
name: clear-stats
description: Judge ClearStack runs against repository evidence. Use when asking whether a run's claimed change landed, was reworked, reverted, or rejected, rather than trusting the run's own report.
---

# Clear stats

A run record says what the agent claims. `clear-stats` answers whether the work held up, from first-party evidence: local Git, GitHub, and parent-run verdicts.

## Collect outcomes

```bash
skills/clear-stats/scripts/outcomes [--runs PATH] [--repo PATH] [--run ID] [--github] [--format json|summary|both]
```

- Reads the run log and correlates each run to commits through the `Clear-Run: <id>` trailer, then to PR, merge, rework, revert, and CI state when available.
- `--github` adds PR merge, review, and CI state through `gh`. Off by default; every `gh` failure is recorded as unavailable evidence, never as a negative outcome.
- `--repo` overrides the repository; by default each run is judged in the working directory its record captured.

## Result model

Each run in the report carries:

- `self_report`: status and claims from `record end`.
- `outcome`: `landed`, `reworked`, `reverted`, `rejected`, `partially_landed`, `not_landed`, `no_commits`, or `unknown`.
- `confidence`: `verified` when git, GitHub, or a parent verdict decided the outcome; `unverified` when only the self-report exists.
- `evidence`: one entry per source (record, git, github), each marked available or unavailable with a note.
- `parent_confirmation` / `child_confirmations`: verdicts written with `record confirm`. A Clear CI repair child its parent rejected is outcome `rejected`, whatever git shows.

Missing or unreadable evidence stays `unknown`. It is never collapsed into zero or a guessed outcome.
