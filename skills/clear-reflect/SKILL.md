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

Prints a JSON report and a short human summary. Run with `--format json` for machine-readable output only, `--format summary` for the detailed terminal text, or `--format discord` for one compact Discord message.

```bash
scripts/mine --format json --output report.json
```

By default it reads `~/.hermes/state.db` and `~/.local/state/clearstack/runs.jsonl`. Pass `--db` or `--runs` to override.

For the Context churn section only, run `scripts/churn-report`. It calls `mine --format summary` with the existing source selection, including profile state databases. Miner stderr remains visible, and a miner failure keeps its nonzero exit status without printing a partial report. A summary without a Context churn section also fails.

When testing these commands, use a stub miner or set `HOME` to a temporary directory. Passing `--db` alone does not isolate the miner's profile scans.

## Detectors

### Review outcomes

Compare review passbacks using Kanban board events, worker run intervals, and
`session_model_usage` across the default and profile databases. The report includes:

- First-review passbacks divided by resolved first reviews, with pending reviews shown separately.
- Review rounds per card, including cards still in review.
- Returns from the human review lane after AI approval, divided by resolved human handoffs.
- Median elapsed time and input, cache, and output tokens through the first AI approval,
  with separate sample sizes for approvals and cards with complete usage.
- Rates by the implementer and reviewer models that actually ran. Multiple models in one
  run remain a mixed group. Missing attribution stays unknown; a configured model is never
  credited as if it ran. Auxiliary calls do not determine the main model group.

The comparison boundary comes from `~/.hermes/scripts/review-baseline.json` when present:

```json
{"changed_at": "2026-01-01T00:00:00Z", "description": "Profile model configuration changed"}
```

Override it with `scripts/mine --review-change-at 2026-01-01T00:00:00Z --format summary`.
Without a boundary, the report shows all available review history. Cards whose work spans
the boundary form a separate `crossed_change` group. Model pairs remain separate by board
and cohort. The JSON and full summary contain the comparison; the Discord summary shows
the overall first-review count and pending count.

These are workflow measurements, not a controlled model comparison. A human-lane reopen
records a return, not proof that the AI reviewer missed a defect. Completion after a handoff
resolves that handoff; it does not prove who clicked Done. Legacy per-model usage may have
been backfilled from session totals, so historical attribution has that limitation. Missing
session links or token receipts exclude a card from the token median rather than making it free.

### Oversized tool results

Flag tool results over 20K chars, grouped by tool name and command shape, so a guard can cap, filter, or redirect them to a file.

### Repeated identical expensive commands

Flag the same normalized command run 3+ times in one session. When the repeats span a compaction event (a `_compressed_summary` message in the same session), they are flagged as compaction-adjacent: the signature of post-compaction state loss.

### Context churn

Measure where kanban card tokens actually go, across the default state db and every profile state db. Three signals:

1. **Restart churn.** Worker sessions are grouped into cards by the first user message (`work kanban task t_x`). Cards with 3+ runs are churned: each restart re-reads the card and the same files from cold. The report gives the churned-card count, their share of all card tokens, and the top cards with titles and boards from the kanban board dbs.
2. **Resend amplification.** Input-side tokens (fresh plus cache read plus cache write) per output token, per session. Every model call resends the whole conversation, so the ratio marks runs where context resend did the spending. Flagged above 200x and 1M input-side tokens.
3. **kanban_show refetch.** Card bodies and handoffs re-fetched mid-run: call count, sessions that fetched more than once, and approximate tokens.

Each signal ends in a proposal (triage routing, durable handoffs, worker_context caps, turn budgets). The detector proposes, never applies.

### Unused skills

Flag installed skills that never appear in tool-call history (`skill_view`, `skill_manage`, `read_file`/`patch`/`search_files`/`write_file` under a skills directory) across the default state db and every profile state db, and are not referenced by agent-hooks, scripts, or kanban card `skills` pins. Reports per-skill catalog cost (name plus description length) and total cost so the operator sees prune candidates. A keep-list inside the mine script marks seasonal skills as keep-only; the detector proposes, never uninstalls.

### Domain fit

Audit whether domain-separated agents stay in their domains. The detector reads `~/.config/clearstack/domain-map.yaml` (or `$XDG_CONFIG_HOME/clearstack/domain-map.yaml`), which declares each domain's profiles, skills, and command signals. The map is per-user config; start from `references/domain-map.example.yaml`. Pass `--domain-map` to override the map path.

Four checks, per profile:

1. **Catalog cost and used-vs-unused skills.** Reuses the per-profile skill-usage machinery to show how many of a domain's skills each lane actually uses.
2. **Cross-domain skill use.** A lane opening a skill owned by another domain (via `skill_view` or `skill_manage`).
3. **Cross-domain work.** Another domain's command signals in a lane's terminal tool history (regex match against `tool_calls` in each profile's state db).
4. **Routing mismatch.** Kanban cards whose title or body match one domain's signals but are assigned to a profile in another domain (across all board dbs).

The report also includes a **domain pressure** list: unassigned domains ranked by signal hits in other profiles. This is the evidence for when a new domain earns its own lane.

A profile with no domain assignment in the map is audited as generalist and is never flagged for using anything.

### Lane ideation

Discover lane-split candidates from the work itself. The detector fingerprints every session from state.db (tool-name mix, normalized command shapes, path prefixes from file arguments, repo roots, skills opened), clusters those fingerprints over weekly windows using Jaccard similarity on top-N signal terms, and reports coherent, recurrent, volume-sufficient, misplaced clusters as candidates.

Four gates, all must hold:

1. **Coherent:** the cluster's dominant signal appears in at least half of its sessions.
2. **Recurrent:** the cluster appears in two or more consecutive weekly windows, measured from message timestamps.
3. **Volume:** at least three sessions or one thousand tokens in the cluster.
4. **Misplaced:** the majority of the cluster's sessions ran in profiles whose domain does not match the cluster's inferred domain.

The report includes each candidate's dominant signals, session count, which profiles the sessions ran in, and paste-ready YAML for the operator to add under `candidates:` in the domain map. The detector proposes, never applies.

## On each finding

1. Read the report and the affected session or run record.
2. **Actionable and local:** a guard (a size cap, a memoization check, a pre-compaction snapshot) fits in one file and one test. Draft the guard and open a card for it.
3. **Broad or structural:** the pattern touches multiple harnesses or needs a schema change. File a finding comment on the reflect card and let a human route it.
