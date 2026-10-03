---
name: clear-mode
description: ClearStack's working mode. Use for non-trivial engineering work (investigating, fixing, building, refactoring, reviewing, shipping, resuming) or when told to apply clear-mode.
---

# Clear mode

Code matters less now than the context and transparency around it. Clear mode keeps six pillars visible, both in how an agent run works and in the software it changes:

- **Context:** what the next reader needs to act.
- **Observation:** what actually happened, shown with evidence.
- **Comprehension:** whether a reader can follow the code and the run.
- **Maintenance, repairability, mutability:** whether the software can be kept running, fixed when it breaks, and changed without fear.

Once invoked, clear mode stays on for the rest of the session. Apply it to each new non-trivial task. A casual question or quick lookup doesn't need it, and the operator can switch it off by saying so.

## Precedence

The repo's `AGENTS.md` or `CLAUDE.md` and the operator's instructions win wherever they are stricter than this skill. Clear mode decides only what they leave open. When a repo rule gates an action that clear mode would take on its own (a commit, a push, a PR), follow the repo rule.

## Every run

See [`references/every-run.md`](references/every-run.md) for the full steps. In brief:

1. **Open the run record.** Run `scripts/record start`. Done when you hold an id.
2. **Pick principles and playbooks.** Open each file you rely on before you act on it. Done when every one has been read this session.
3. **Work to done autonomously.** See [`references/autonomy.md`](references/autonomy.md). Done when a stop condition holds.
4. **Resume after compaction if needed.** Run `scripts/record resume <id>` after a compaction handoff. Treat verified claims as already proven.
5. **Close the run record.** Run `scripts/record end`. Done when every claim is recorded.
6. **Reply.** Report each state separately, with evidence, in the `clear-voice` style.

## Autonomy

See [`references/autonomy.md`](references/autonomy.md). In brief: proceed on reversible work without asking. Stop and hand back when the next action is irreversible, a product call remains, two fixes sharing one premise have failed, access is missing, or the work is done.

## Unattended

When nobody is watching the run (a queued card, a loop, "I'm stepping away"):

- Keep going until a stop condition holds. Ending a turn with work left and no stop condition is an early finish.
- Commit at each verifiable unit so a crash loses at most one unit.
- Write every non-obvious decision to the record as a note, since nobody saw you make it.

## Principles

Each file in `references/principles/` gives the rule, when it applies, the decision it changes, and a counter-example.

**Context**
- `leave-context-behind`: making a non-obvious decision, stopping early, or changing code whose reason the diff does not show.
- `load-context-deliberately`: starting a task, entering unfamiliar code, or facing a large read.

**Observation**
- `separate-the-states`: reporting status or ending a run.
- `claims-carry-evidence`: writing any claim that something is done, works, or was verified.
- `record-dont-grade`: ending a run or describing your own work.
- `prove-on-the-real-artifact`: about to declare a change done.
- `ship-what-you-verified`: handing over a build, branch, or deploy.

**Comprehension**
- `model-the-domain`: writing stateful or branching logic, or repeating a shape assumption.
- `test-behavior`: writing, changing, or keeping a test.
- `minimize-reader-load`: adding an abstraction, tracing hard code, naming.

**Maintenance**
- `less-code`: sizing a change or adding a file, dependency, flag, or abstraction.
- `guards-over-reminders`: something went wrong, or an instruction is being written a second time.
- `budget-the-context`: adding to a skill, writing a long run, or loading detail that only one step needs.

**Repairability**
- `fix-at-the-right-layer`: debugging, or the same fix is about to land in a second place.
- `fail-loudly-and-locally`: writing error handling, parsing input, or adding a fallback.
- `prefer-reversible-changes`: planning a change to data, a public contract, or work spanning PRs.

**Mutability**
- `experiment-before-asking`: about to ask which approach, what something does, or whether it will work.
- `parallelize-independent-work`: starting a task with two or more independent, parallelizable sub-tasks.

## Playbooks

Each file in `references/playbooks/` gives the trigger, principles, steps, and stop conditions for a common task shape.

- **Investigate:** [`references/playbooks/investigate.md`](references/playbooks/investigate.md). A symptom, error, or behavior needs explanation.
- **Bug-fix:** [`references/playbooks/bug-fix.md`](references/playbooks/bug-fix.md). A specific, reproducible failure needs a code change.
- **Feature:** [`references/playbooks/feature.md`](references/playbooks/feature.md). New behavior is needed and the interface is not yet fixed.
- **Review:** [`references/playbooks/review.md`](references/playbooks/review.md). A diff or PR needs judgment before it merges.
- **Ship:** [`skills/ship/SKILL.md`](../ship/SKILL.md). A pull request has been opened or updated and needs to reach merge.
- **Pickup/handoff:** [`references/playbooks/pickup-handoff.md`](references/playbooks/pickup-handoff.md). A parked run or handoff note needs to be resumed.

## Harness notes

- **Claude Code:** this skill's directory is the "Base directory" shown when it loads. Ask the stop-condition decision with `AskUserQuestion`.
- **Codex, Hermes, and others:** this skill's directory is the folder this file was read from. Ask the stop-condition decision in the reply, or through the harness's blocking mechanism (for example a Hermes card's `needs_input` block).
