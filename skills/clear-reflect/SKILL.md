---
name: clear-reflect
description: Batch mining pass over agent history that turns repeated waste into proposed principles, guards, or scripts.
---

# Clear reflect

Agent runs accumulate waste: oversized tool results that refill the context window, identical verification commands re-run after compaction, and other repeated patterns that cost time and tokens. `clear-reflect` mines the history systematically and proposes guards, never applying them automatically.

## How it runs

Batch, never a per-turn hook. Three invocation modes:

- **On demand:** load this skill and run `scripts/mine` against a window of history.
- **On a cadence:** a scheduled kanban card or cron runs the same mining and files the report.
- **It proposes, never applies.** Principles, guards, and scripts come out as report findings or draft cards. Nothing edits a skill or hook without a human or a fresh card.

## Use

From this skill's directory:

```bash
scripts/mine
```

Prints a JSON report and a short human summary. Run with `--format json` for machine-readable output only, or `--format summary` for the human text only.

```bash
scripts/mine --format json --output report.json
```

By default it reads `~/.hermes/state.db` and `~/.local/state/clearstack/runs.jsonl`. Pass `--db` or `--runs` to override.

## Detectors

### Oversized tool results

Flag tool results over 20K chars, grouped by tool name and command shape, so a guard can cap, filter, or redirect them to a file.

### Repeated identical expensive commands

Flag the same normalized command run 3+ times in one session. When the repeats span a compaction event (a `_compressed_summary` message in the same session), they are flagged as compaction-adjacent: the signature of post-compaction state loss.

## On each finding

1. Read the report and the affected session or run record.
2. **Actionable and local:** a guard (a size cap, a memoization check, a pre-compaction snapshot) fits in one file and one test. Draft the guard and open a card for it.
3. **Broad or structural:** the pattern touches multiple harnesses or needs a schema change. File a finding comment on the reflect card and let a human route it.
