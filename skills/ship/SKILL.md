---
name: ship
description: Playbook for shipping a PR. Use after opening or updating a pull request to watch CI, react to failures, and reach merge.
---

# Ship

Trigger: a pull request has been opened or updated and needs to reach merge.

## Principles

- `ship-what-you-verified`
- `prove-on-the-real-artifact`
- `separate-the-states`
- `claims-carry-evidence`
- `fail-loudly-and-locally`

## Steps

1. Open a run record with `--playbook ship`.
2. Verify the PR is open and record its state:
   ```bash
   scripts/ship check --repo OWNER/REPO --pr N
   ```
   Record the PR URL, head SHA, and branch with `record note`.
3. Start CI watching:
   ```bash
   ../clear-ci/scripts/watch --repo OWNER/REPO --pr N
   ```
4. For each response line from the watcher:
   - `dispatch_repair`: spawn one isolated repair subagent with the whole record as its brief. Record the failure with `record note` and update focus with `record focus`. The repair worker commits and pushes to the PR branch and never opens another pull request.
   - `request_operator_decision`: record the evidence with `record note`, ask the operator for one decision, and keep watching.
5. Update `record focus` as the run state shifts: `watching`, `repairing`, `waiting-for-operator`, `verifying`.
6. When CI reaches a terminal state for the current head:
   - If green, treat it as evidence, not a substitute for review. Read the diff and check the intended artifact.
   - If red with unresolved failures, record each one and stop.

## Stop conditions

- The PR is merged.
- A product or preference call remains that no experiment can settle.
- Two fixes that share one premise have failed the same check.
- The next step is irreversible and nobody has granted it.
- CI is green on the current head, the diff has been reviewed, and the intended artifact checks out.

## Harness notes

- **Hermes:** run `watch` in the background with a line-match notification. React to each `dispatch_repair` with `delegate_task` or a kanban child card assigned to the repair profile. Fill `parent_run_id` with your current run-record id.
- **Claude Code:** run `watch` in the background. React to each response line as it prints; use the Task tool for repair delegation.
- **Codex:** run `watch` in the background. React to each response line; use a subagent invocation for repair delegation.
- A harness with no delegation mechanism may fix `dispatch_repair` inline on the same branch, since the response already forbids opening another pull request.
