# Every run

## Task source

For tracked work, read the current task from its task-tracking platform before planning or changing code. Use the supplied task URL or the repository's configured tracker to identify the platform, then use its available integration. A task ID alone does not identify the platform. If the source is missing or inaccessible, ask for it rather than guessing. Use the current task as the specification, subject to the operator's instructions and repository rules. Treat copied card descriptions and handoff summaries as context, not replacements for the source. Keep the task ID and URL in the run context instead of copying the full description. Ad hoc work uses the operator's request and needs no tracker.

## Steps

1. **Open the run record.** From this skill's directory, run `scripts/record start --task "<the task in one line>" --playbook <name or none>` and keep the printed run id. Done when you hold an id.
2. **Pick principles and playbooks.** Read the index in `SKILL.md` and open each principle file, and any playbook that applies, before you act on it. Done when every principle and playbook you rely on has been read this session.
3. **Work to done autonomously.** See `references/autonomy.md`. Add `--trailer "Clear-Run: <id>"` to every commit the run makes. Log each non-obvious decision with `scripts/record note <id> "<decision, alternatives, why>"`. When the operator's request or the open question changes, a follow-up redirects the work, you finish one sub-goal and move to the next, or you are blocked on a specific decision, call `scripts/record focus <id> "<the current request or question, one line>"` so a long run's goal stays visible instead of buried under the output since it was last stated.
4. **Resume after compaction if needed.** If the harness compacts context and the session continues with a handoff, run `scripts/record resume <id>` first. Treat every claim it lists as verified as already proven. Do not re-run the evidence commands behind them. Re-verify only the claims it lists as unverified.
5. **Close the run record.** Run `scripts/record end <id> --status done|parked|abandoned`, with one `--verified "<claim>: <evidence>"` per proven claim, one `--unverified "<claim>"` per claim you could not prove, `--needs "<decision>"` when parked, and `--pr` when there is one. Done when every claim your reply will make appears in the record as verified or unverified.
6. **Reply.** Report each state separately (see **separate-the-states**), put evidence beside each claim, and name each principle that changed a decision and the decision it changed. Write the reply, commit messages, PR bodies, and record notes in the `clear-voice` style.
