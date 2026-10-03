---
name: clear-ci
description: Use instead of `gh pr checks --watch` or `gh run watch` after opening or updating a PR. Responds to each real CI failure as it happens instead of blocking until the whole run finishes.
---

# Clear CI

`gh pr checks --watch` and `gh run watch` block until every job in every workflow finishes before you see anything. The first real failure is often visible minutes before the stack as a whole completes, and that time is lost waiting.

`scripts/watch` polls job-level status for a PR's head commit and prints one JSON line the moment a job reaches `conclusion: failure`, followed by one response line that says what to do about it. It does not report a job that GitHub itself marked `skipped` because a `needs:` dependency already failed, so a chain reaction downstream of one real break does not read as several.

The event-to-response contract, including the full record schema and the harness adapter, lives in [`references/contract.md`](references/contract.md). In brief, each response is one of:

- `dispatch_repair`: the failed-log tail names a file the PR changed. Start one isolated repair subagent with the record as its brief. It commits and pushes to the PR's branch and never opens another pull request.
- `request_operator_decision`: the failure looks like runner/infra trouble or cannot be tied to the diff. Record the evidence, ask the operator for one decision, and change no code for this failure.

## Use

From this skill's directory:

```bash
scripts/watch --repo OWNER/REPO --pr 123
```

Prints one failure line and one response line per newly failed job, in the order jobs complete:

```json
{"run_id": 123456, "job_id": 789, "job_name": "test (18.x)", "workflow": "CI", "html_url": "https://github.com/OWNER/REPO/actions/runs/123456/job/789"}
{"response": "dispatch_repair", "classification": "pr-caused", "evidence": ["src/app.py"], "run_id": 123456, "job_id": 789, "job_name": "test (18.x)", "workflow": "CI", "html_url": "https://github.com/OWNER/REPO/actions/runs/123456/job/789", "pr_url": "https://github.com/OWNER/REPO/pull/123", "head_sha": "abc123", "branch": "fix-thing", "changed_files": ["src/app.py"], "log_tail": "...", "instructions": "...", "spawned_by": "clear-ci", "parent_run_id": null}
```

Exits 0 once every workflow run for the PR's current head SHA has reached a terminal status (`success`, `failure`, or `cancelled`). Exits 1 if `--max-seconds` (default 3600) passes first.

Run it in the background with a line-match notification so a real failure interrupts you; react to each response line as it prints. One handled failure does not stop the loop: independent failures in other jobs or runs each get their own event and response.

## On each response line

1. `dispatch_repair`: spawn the repair worker through your harness's delegation mechanism (Hermes `delegate_task`, Claude Code Task tool, Codex subagent) with the whole record as its brief. Fill `parent_run_id` with your current run-record id and pass `spawned_by` through to the worker's `record start`. If you are mid-task and the fix is small, you may fix inline on the same branch instead; the response already forbids a second pull request.
2. `request_operator_decision`: do not push a guess. Ask the operator what to do and say why the failure looks unrelated (base-red, flaky, runner/infra, or an unrelated workflow), citing the `evidence` field. Keep watching; one ambiguous failure does not stop the loop.

## Pitfall

`gh pr checks` aggregates at the check level across workflows and does not expose per-job `needs:` relationships. `scripts/watch` reads `gh run view --json jobs` per run instead, which carries each job's own `conclusion`.
