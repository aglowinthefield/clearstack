---
name: clear-ci
description: Use instead of `gh pr checks --watch` or `gh run watch` after opening or updating a PR. Reacts to each real CI failure as it happens instead of blocking until the whole run finishes.
---

# Clear CI

`gh pr checks --watch` and `gh run watch` block until every job in every workflow finishes before you see anything. The first real failure is often visible minutes before the stack as a whole completes, and that time is lost waiting.

`scripts/watch` polls job-level status for a PR's head commit and prints one line of JSON the moment a job reaches `conclusion: failure`, instead of waiting for the run to end. It does not report a job that GitHub itself marked `skipped` because a `needs:` dependency already failed, so a chain reaction downstream of one real break does not read as several.

## Use

From this skill's directory:

```bash
scripts/watch --repo OWNER/REPO --pr 123
```

Prints one JSON line per newly failed job, in the order jobs complete:

```json
{"run_id": 123456, "job_id": 789, "job_name": "test (18.x)", "workflow": "CI", "html_url": "https://github.com/OWNER/REPO/actions/runs/123456/job/789"}
```

Exits 0 once every workflow run for the PR's current head SHA has reached a terminal status (`success`, `failure`, or `cancelled`). Exits 1 if `--max-seconds` (default 3600) passes first.

Run it foreground when you have nothing else to do; react to each line as it prints. Run it in the background with a line-match notification when you want to keep working and be interrupted only on a real failure.

## On each failure line

1. Read the failing job's log and the PR's changed files:
   ```bash
   gh run view <run_id> --repo OWNER/REPO --job <job_id> --log-failed
   gh pr diff <pr> --repo OWNER/REPO --name-only
   ```
2. **Caused by this PR's diff** (the failing path is a changed file, or the error names a symbol the diff touches): fix it on the PR's branch now and push. You already hold the diff and repo context; do not hand this to a subagent unless you are mid-task elsewhere and want the fix running in parallel without blocking your current thread, in which case tell it explicitly to fix on the existing branch and not open a new PR.
3. **Not obviously caused by this PR's diff** (flaky test, pre-existing failure on the base branch, runner/infra issue, unrelated workflow): do not push a guess. Ask the operator what to do and say why the failure looks unrelated. Keep watching; one ambiguous failure does not stop the loop.

## Pitfall

`gh pr checks` aggregates at the check level across workflows and does not expose per-job `needs:` relationships. `scripts/watch` reads `gh run view --json jobs` per run instead, which carries each job's own `conclusion`.
