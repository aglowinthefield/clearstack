<p align="center">
  <img src="assets/logo.jpg" alt="Pink orchids displayed on a vintage Macintosh Classic" width="160">
</p>

<h1 align="center">ClearStack</h1>

<p align="center">Agent skills for seeing what your agents, and the software they write, are actually doing.</p>

---

Agents write code faster than anyone can read it, so code is no longer the scarce part. What matters is whether you can see what is going on: inside an agent's run, and in the software it leaves behind. ClearStack is a set of agent skills built on six pillars.

New pillars, for working with agents:

- **Context:** what the next reader, human or agent, needs to act.
- **Observation:** what actually happened, shown with evidence.
- **Comprehension:** whether a reader can follow the code and the run.

Pillars of effective software design:

- **Maintenance:** keeping it running with little effort.
- **Repairability:** finding and fixing what broke.
- **Mutability:** changing it without fear.

## Install

ClearStack is a folder of plain [Agent Skills](https://agentskills.io). It works in Claude Code, Codex, Hermes, and any other agent that reads `SKILL.md`.

```bash
npx skills add aglowinthefield/clearstack -g
```

To have agents apply it without being asked, add this line to a repo's `AGENTS.md` or `CLAUDE.md`, or to your global one:

```markdown
Apply the `clear-mode` skill to every non-trivial engineering task, and write all output in the `clear-voice` style. Repo instructions still win where they are stricter.
```

## How it works

`clear-mode` is the entry point. On every non-trivial task the agent:

1. Opens a run record with `scripts/record start`.
2. Reads the principles that apply to the task.
3. Works to done without checking in, logging each non-obvious decision to the record.
4. Closes the record, listing each claim as verified (with its evidence) or unverified.
5. Replies with each state kept separate: changed locally, committed, pushed, merged, verified, approved.

The agent stops and hands back only when:

- the next step is irreversible or outward-facing and nobody has granted it,
- a product or preference call remains that no experiment can settle,
- two fixes that share one premise have failed the same check,
- it lacks access it needs, or
- the work is done and proven.

When it stops early, it leaves the work committed with a handoff note and names the single decision it needs. Your repo's own rules win wherever they are stricter than ClearStack's.

## Clear voice

`clear-voice` is the output style for everything an agent writes: replies, commit messages, PR bodies, handoff notes, and run-record entries. It leads with the answer, keeps length matched to the ask, and drops stock AI vocabulary, filler, chatbot phrases, and em dashes. It governs content and density, so an operator-chosen persona still works.

The rules are numbered in [`skills/clear-voice/SKILL.md`](skills/clear-voice/SKILL.md). `scripts/voice-check` flags the ones a script can see, with file, line, and rule id:

```bash
skills/clear-voice/scripts/voice-check PR_BODY.md
```

The test suite runs it over every Markdown file in this repo.

## Principles

Each principle is one short file in [`skills/clear-mode/references/principles/`](skills/clear-mode/references/principles/) giving the rule, when it applies, the decision it changes, and a counter-example.

| Pillar | Principles |
|---|---|
| Context | [leave-context-behind](skills/clear-mode/references/principles/leave-context-behind.md), [load-context-deliberately](skills/clear-mode/references/principles/load-context-deliberately.md) |
| Observation | [separate-the-states](skills/clear-mode/references/principles/separate-the-states.md), [claims-carry-evidence](skills/clear-mode/references/principles/claims-carry-evidence.md), [record-dont-grade](skills/clear-mode/references/principles/record-dont-grade.md), [prove-on-the-real-artifact](skills/clear-mode/references/principles/prove-on-the-real-artifact.md), [ship-what-you-verified](skills/clear-mode/references/principles/ship-what-you-verified.md) |
| Comprehension | [model-the-domain](skills/clear-mode/references/principles/model-the-domain.md), [test-behavior](skills/clear-mode/references/principles/test-behavior.md), [minimize-reader-load](skills/clear-mode/references/principles/minimize-reader-load.md) |
| Maintenance | [less-code](skills/clear-mode/references/principles/less-code.md), [guards-over-reminders](skills/clear-mode/references/principles/guards-over-reminders.md) |
| Repairability | [fix-at-the-right-layer](skills/clear-mode/references/principles/fix-at-the-right-layer.md), [fail-loudly-and-locally](skills/clear-mode/references/principles/fail-loudly-and-locally.md), [prefer-reversible-changes](skills/clear-mode/references/principles/prefer-reversible-changes.md) |
| Mutability | [experiment-before-asking](skills/clear-mode/references/principles/experiment-before-asking.md) |

## Run records

Every clear-mode run appends to `~/.local/state/clearstack/runs.jsonl` on your machine. The log never leaves it. A record holds the task, the harness and session, the git state at start and end, the decision trail, and the claims:

```json
{"ts": "2026-09-30T21:00:51+00:00", "event": "end", "run": "cr-20260930-a2bd26", "status": "done",
 "verified": ["record script behaves: unittest 3/3 pass"],
 "unverified": ["clear-mode loads and triggers in a fresh Codex or Hermes session"],
 "needs": null, "pr": "https://github.com/aglowinthefield/clearstack/pull/1"}
```

Commits made during a run carry a `Clear-Run: <id>` trailer, which links GitHub history back to the run. The agent never grades its own work. Whether it held up (merged unchanged, reworked, reverted) comes later from GitHub and the session transcripts.

## Local dashboard

Start the read-only run dashboard with:

```bash
python3 -m clearstack.dashboard
```

It serves only on `127.0.0.1:8765` and reads `~/.local/state/clearstack/runs.jsonl` (or `$XDG_STATE_HOME/clearstack/runs.jsonl`). It makes no network requests and does not change the log. This first version shows run status, duration, decision notes, and claims. Token and tool-call telemetry is not collected by the current run log, so the dashboard labels it as unavailable rather than showing zero.

The dashboard should also preserve the user's original request and pending decisions through long agent output, so the current goal does not get buried. This first version reads run records only and does not capture conversation text.

## Status

| | Piece | State |
|---|---|---|
| 1 | `clear-mode`, principles, `scripts/record` | merged |
| 1b | `clear-voice` output style and `voice-check` | merged |
| 2 | Playbooks: investigate, bug-fix, feature, review, ship, pickup/handoff | planned |
| 3 | `clear-stats`: outcomes, claim vs proof, rework, corrections, and cost across Claude Code, Codex, Hermes, and GitHub | planned |
| 4 | `clear-reflect`: mine transcripts for repeated corrections and repeated tool-call chains, and propose principles, guards, or scripts | planned |
| 5 | Local dashboard: read-only view of run records | in progress; token and tool-call telemetry still needs a local source |

## Develop

Link the skill from a checkout so edits take effect without reinstalling:

```bash
git clone https://github.com/aglowinthefield/clearstack ~/code/clearstack
ln -s ~/code/clearstack/skills/clear-mode ~/.agents/skills/clear-mode
python3 -m unittest discover -s tests
```

Claude Code reads `~/.claude/skills`, so link it there too. Everything is standard-library Python, including the logo: `python3 assets/make_logo.py` redraws `assets/logo.png`.

## Credit

Inspired by [pstack](https://github.com/cursor/plugins/tree/main/pstack) by poteto.

## License

MIT
