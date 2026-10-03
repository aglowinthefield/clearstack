# Clear CI event-to-response contract

This contract binds a ClearStack agent that has opened or updated a pull request and started `scripts/watch`. It fixes what the watcher emits, what each event triggers, and who acts. The watcher prints records; the agent's harness acts on them.

## Event

One NDJSON line per newly failed job, in the order jobs complete:

```json
{"run_id": 123456, "job_id": 789, "job_name": "test (18.x)", "workflow": "CI", "html_url": "https://github.com/OWNER/REPO/actions/runs/123456/job/789"}
```

Rules:

- Exactly one event per `(run_id, job_id)`. `job_id` is GitHub's per-attempt job id, so a retried attempt is a new event and a repeated poll of the same attempt is not.
- A job GitHub marks `skipped` because a `needs:` dependency failed never produces an event. One real break does not read as several.
- Events keep arriving after earlier ones are handled. The loop ends when every run for the PR's head SHA is terminal or `--max-seconds` passes.

## Response

Exactly one response line follows each event line. Two shapes exist.

`dispatch_repair`: the failed-log tail names a file the PR changed, so the failure belongs to this diff.

```json
{"response": "dispatch_repair", "classification": "pr-caused", "evidence": ["src/app.py"],
 "run_id": 123456, "job_id": 789, "job_name": "test (18.x)", "workflow": "CI",
 "html_url": "https://github.com/OWNER/REPO/actions/runs/123456/job/789",
 "pr_url": "https://github.com/OWNER/REPO/pull/123", "head_sha": "abc123",
 "branch": "fix-thing", "changed_files": ["src/app.py"], "log_tail": "...last 80 log lines...",
 "instructions": "Fix the failing job 'test (18.x)' on branch 'fix-thing' of OWNER/REPO. Commit and push to that branch. Never open another pull request.",
 "spawned_by": "clear-ci", "parent_run_id": null}
```

The agent starts one isolated repair subagent per `dispatch_repair` record and hands it the whole record as its brief. The repair worker commits and pushes to `branch`; it never opens another pull request. The agent keeps watching for further events while the repair runs.

`request_operator_decision`: the failure looks like runner or infra trouble, or nothing ties it to the diff.

```json
{"response": "request_operator_decision", "classification": "infra", "evidence": ["the operation was canceled"],
 "run_id": 123456, "job_id": 789, "job_name": "test (18.x)", "workflow": "CI",
 "html_url": "https://github.com/OWNER/REPO/actions/runs/123456/job/789",
 "pr_url": "https://github.com/OWNER/REPO/pull/123", "head_sha": "abc123",
 "branch": "fix-thing", "changed_files": ["src/app.py"], "log_tail": "...last 80 log lines..."}
```

The agent records the evidence and asks the operator for one decision, naming why the failure looks unrelated (base-red, flaky, runner/infra, or an unrelated workflow). It changes no code for this failure and keeps watching.

## Classification

`classify` in `scripts/watch` assigns one verdict per event:

- `pr-caused`: the failed-log tail contains a changed-file path, matched on the full path or its basename. The matched paths are the evidence.
- `infra`: the log tail contains a runner or infra signature from `INFRA_SIGNATURES` (cancelled operations, runner shutdown, rate limits, disk full, killed processes).
- `unknown`: neither matched, or the log could not be read. An unreadable log never blocks a verdict; it classifies `unknown`.

Only `pr-caused` dispatches a repair. The classifier fails toward the operator, so a wrong guess never becomes a pushed fix.

## Harness adapter

The watcher is a shell process and cannot invoke an agent runtime, so spawning the repair worker is the harness's job. Each harness maps `dispatch_repair` to its own delegation mechanism:

- Hermes: `delegate_task` with the record as context, or a kanban child card assigned to the repair profile.
- Claude Code: the Task tool with the record as the subagent prompt.
- Codex: a subagent invocation carrying the record.

The adapter fills `parent_run_id` with the agent's current run-record id and passes it plus `spawned_by` to `record start --parent-run <id> --spawned-by clear-ci`, so the repair run links back to its parent in the run log. A harness with no delegation mechanism handles `dispatch_repair` by fixing inline on the same branch, which the contract allows because the response already forbids opening another pull request.
