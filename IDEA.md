ClearStack: agent skills that make agent runs and the software they produce transparent, built on six pillars (context, observation, comprehension, maintenance, repairability, mutability).

- Ship `clear-mode`, a router skill whose runs work autonomously, stop only on defined conditions, and keep honest run records with evidence for every claim.
- Add playbooks for investigate, bug-fix, feature, review (with a pillar rubric), ship, and pickup/handoff.
- Build `clear-stats` to judge runs from first-party data (merged, reworked, reverted, corrections, cost) across Claude Code, Codex, Hermes, and GitHub.
- Build `clear-reflect` to turn repeated corrections and repeated tool-call chains into principles, guards, or scripts.
- Dogfood it on every task, and fix friction in the stack rather than working around it.
- Track subagents as first-class run data, not flat rows: each run record carries an optional `parent_run_id` (and `spawned_by` source) linking a subagent's session to the parent run that spawned it, so the dashboard renders a run as a parent-child tree. A subagent's reported result is a self-report, not a verified fact, and should show as unverified until the parent run's own output confirms it.
- Encourage subagent delegation for multi-pronged tasks: when work decomposes into independent, parallelizable sub-tasks, surface or prompt fan-out to subagents instead of serial single-agent work. Parent-child tracking is what makes recommending that fan-out safe.
