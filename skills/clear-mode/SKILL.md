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

1. **Open the run record.** From this skill's directory, run `scripts/record start --task "<the task in one line>" --playbook <name or none>` and keep the printed run id. Done when you hold an id.
2. **Pick principles.** Read the index below and open each principle file that applies to this task before you act on it. Done when every principle you rely on has been read this session.
3. **Work to done autonomously.** See **Autonomy**. Add `--trailer "Clear-Run: <id>"` to every commit the run makes. Log each non-obvious decision with `scripts/record note <id> "<decision, alternatives, why>"`.
4. **Close the run record.** Run `scripts/record end <id> --status done|parked|abandoned`, with one `--verified "<claim>: <evidence>"` per proven claim, one `--unverified "<claim>"` per claim you could not prove, `--needs "<decision>"` when parked, and `--pr` when there is one. Done when every claim your reply will make appears in the record as verified or unverified.
5. **Reply.** Report each state separately (see **separate-the-states**), put evidence beside each claim, and name each principle that changed a decision and the decision it changed.

## Autonomy

Proceed on reversible work without asking, and let the operator correct course from the result. Stop and hand back only when one of these holds:

1. The next action is irreversible or reaches outside the workspace (merge, deploy, publish, message someone, delete work you did not create), and neither the repo nor the operator has granted it.
2. A product or preference call remains that no experiment can settle (see **experiment-before-asking**).
3. Two fixes that share one premise have failed the same check. Report the premise instead of writing a third fix built on it.
4. The work needs access you do not have: credentials, a device, an environment.
5. The done condition is met and proven.

On stops 1 to 4, park the work: leave it committed on a branch where the repo allows, write a handoff note (see **leave-context-behind**), end the record as `parked`, and name the single decision you need.

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

**Repairability**
- `fix-at-the-right-layer`: debugging, or the same fix is about to land in a second place.
- `fail-loudly-and-locally`: writing error handling, parsing input, or adding a fallback.
- `prefer-reversible-changes`: planning a change to data, a public contract, or work spanning PRs.

**Mutability**
- `experiment-before-asking`: about to ask which approach, what something does, or whether it will work.

## Harness notes

- **Claude Code:** this skill's directory is the "Base directory" shown when it loads. Ask the stop-condition decision with `AskUserQuestion`.
- **Codex, Hermes, and others:** this skill's directory is the folder this file was read from. Ask the stop-condition decision in the reply, or through the harness's blocking mechanism (for example a Hermes card's `needs_input` block).
