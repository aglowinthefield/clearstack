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

### Unused skills

Flag installed skills that never appear in tool-call history (`skill_view`, `skill_manage`, `read_file`/`patch`/`search_files`/`write_file` under a skills directory) across the default state db and every profile state db, and are not referenced by agent-hooks, scripts, or kanban card `skills` pins. Reports per-skill catalog cost (name plus description length) and total cost so the operator sees prune candidates. A keep-list inside the mine script marks seasonal skills as keep-only; the detector proposes, never uninstalls.

### Domain fit

Audit whether domain-separated agents stay in their domains. The detector reads `references/domain-map.yaml`, which declares each domain's profiles, skills, and command signals. Pass `--domain-map` to override the map path.

Four checks, per profile:

1. **Catalog cost and used-vs-unused skills.** Reuses the per-profile skill-usage machinery to show how many of a domain's skills each lane actually uses.
2. **Cross-domain skill use.** A lane opening a skill owned by another domain (via `skill_view` or `skill_manage`).
3. **Cross-domain work.** Another domain's command signals in a lane's terminal tool history (regex match against `tool_calls` in each profile's state db).
4. **Routing mismatch.** Kanban cards whose title or body match one domain's signals but are assigned to a profile in another domain (across all board dbs).

The report also includes a **domain pressure** list: unassigned domains ranked by signal hits in other profiles. This is the evidence for when a new domain earns its own lane.

A profile with no domain assignment in the map is audited as generalist and is never flagged for using anything.

## On each finding

1. Read the report and the affected session or run record.
2. **Actionable and local:** a guard (a size cap, a memoization check, a pre-compaction snapshot) fits in one file and one test. Draft the guard and open a card for it.
3. **Broad or structural:** the pattern touches multiple harnesses or needs a schema change. File a finding comment on the reflect card and let a human route it.
