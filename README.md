# ClearStack

Agents write code faster than anyone can read it, so the code is no longer the scarce part. What matters is whether you can see what is going on: inside an agent's run, and in the software it leaves behind. ClearStack is a set of agent skills built on six pillars.

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

To have agents apply it without being asked, add this line to a repo's `AGENTS.md` or `CLAUDE.md`:

```markdown
Apply the clear-mode skill to non-trivial engineering work.
```

## Skills

| Skill | Use it when |
|---|---|
| [`clear-mode`](skills/clear-mode/SKILL.md) | Starting any non-trivial task. It applies the principles, runs autonomously until a defined stop condition, and keeps a run record. |

## Run records

Every clear-mode run writes a record to `~/.local/state/clearstack/runs.jsonl` on your machine: the task, the claims it made with their evidence, and where it stopped. Its commits carry a `Clear-Run: <id>` trailer. The agent never grades its own work. Outcomes (merged, reworked, reverted) come later from GitHub and the session transcripts.

## Credit

Inspired by [pstack](https://github.com/cursor/plugins/tree/main/pstack) by poteto.

## License

MIT
