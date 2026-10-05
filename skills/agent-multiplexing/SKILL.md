---
name: agent-multiplexing
description: Coordinate parallel coding agents without repository races.
---

# Agent multiplexing

Use parallel agents when their work is independent. Keep one coordinator responsible for the dependency graph, repository ownership, integration, and the final verification.

## Use

Use this skill when a task has two or more independent investigation, review, or implementation paths.

Do not use it for a small task with one clear path, or for tasks whose later steps need the earlier result.

## Procedure

1. Draw the dependency graph before delegation. Delegate only leaf tasks whose outputs do not change another task's scope. Done when every task has an owner, a bounded output, and no unlisted dependency.
2. Choose one coordinator. The coordinator owns the acceptance criteria, integration branch, final verification, and decisions that affect more than one worker. Done when workers cannot independently create competing plans for the same work.
3. Assign repository ownership explicitly. Give each editing worker a separate worktree and a non-overlapping file or subsystem scope. If worktrees are unavailable, designate one writer and make every other worker read-only. Done when no two workers can change the same checkout concurrently.
4. Give every worker a complete brief: task, repository path or worktree, allowed files, excluded files, acceptance criteria, required checks, and return format. Done when a worker can start without the parent conversation.
5. Link delegated ClearStack runs to the coordinator. Start each child with `scripts/record start --task "..." --parent-run <parent-run-id> --spawned-by <harness>`. Done when the dashboard can render the parent-child relationship.
6. Collect results at the coordinator. Treat each worker's report as unverified until the coordinator reads the diff, resolves overlap, and runs the required checks against the integrated artifact. Record the result with `scripts/record confirm <parent-run-id> <child-run-id> --status accepted|rejected --reason "..."`. Done when every acceptance criterion has one authoritative result.
7. End workers before changing shared state. Do not merge, rebase, or delete worktrees while a worker owns them. Done when each worker has returned or been stopped before integration begins.

## Task brief

Use this shape for each worker:

```text
Goal:
Repository and worktree:
Owned scope:
Excluded scope:
Acceptance criteria:
Required checks:
Return: changed files, evidence, open risks, and child run id.
```

## Pitfalls

- Do not use two schedulers to launch editing agents against the same checkout. The schedulers cannot coordinate ownership.
- Do not delegate two tasks that change the same abstraction just because their file lists differ.
- Do not let a child merge or publish the coordinator's work unless the brief grants that authority.
- Do not treat a child report as proof. A parent run confirms the result against the integrated artifact.

## Verification

Before closing the coordinator run, verify that every editing worker had separate ownership, every child run has a parent link, no accepted result overlaps unresolved work, and the integrated artifact passes the required checks.
