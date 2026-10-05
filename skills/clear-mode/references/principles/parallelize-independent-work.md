# Parallelize independent work

Pillar: mutability

**Rule.** When a task decomposes into sub-tasks that do not depend on each other's output, delegate them to subagents in parallel instead of working through them one at a time. Serial work on independent pieces costs wall-clock time the dependency graph doesn't require.

**Applies when.** About to start a task with two or more independent, parallelizable sub-tasks (e.g. research across several sources, parallel investigation of unrelated files, independent build-and-verify steps).

**Changes.** You delegate the independent pieces as subagents and continue with the rest, instead of running them in sequence yourself. Pass your own run id to each subagent's context so it opens its run record with `scripts/record start --parent-run <your-run-id> --task "..."`, linking it into your run's tree instead of logging as an unrelated flat run. A subagent's reported result is a self-report, not verified evidence; treat it like any other claim in `claims-carry-evidence` until you confirm it against the real artifact.

**Counter-example.** Investigating three unrelated bug reports one after another in the same session when nothing in the second depends on the first's findings.
