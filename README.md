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

## Clear CI

`clear-ci` replaces `gh pr checks --watch` and `gh run watch` after opening or updating a PR. Those block until every job in every workflow finishes; `clear-ci`'s `scripts/watch` polls job-level status instead and prints each real failure the moment it happens, so the agent can start fixing before the rest of the stack completes. A job GitHub marks `skipped` because a `needs:` dependency already failed is not reported, so one real break downstream of a chain does not read as several.

Each failure line is followed by one response line: `dispatch_repair` when the failed-log tail names a file the PR changed (the agent starts one repair subagent on the same branch), or `request_operator_decision` when it looks like infra trouble or cannot be tied to the diff. The event-to-response contract is in [`skills/clear-ci/references/contract.md`](skills/clear-ci/references/contract.md).

```bash
skills/clear-ci/scripts/watch --repo OWNER/REPO --pr 123
```

See [`skills/clear-ci/SKILL.md`](skills/clear-ci/SKILL.md) for the fix-or-ask decision on each failure.

## Principles

Each principle is one short file in [`skills/clear-mode/references/principles/`](skills/clear-mode/references/principles/) giving the rule, when it applies, the decision it changes, and a counter-example.

| Pillar | Principles |
|---|---|
| Context | [leave-context-behind](skills/clear-mode/references/principles/leave-context-behind.md), [load-context-deliberately](skills/clear-mode/references/principles/load-context-deliberately.md) |
| Observation | [separate-the-states](skills/clear-mode/references/principles/separate-the-states.md), [claims-carry-evidence](skills/clear-mode/references/principles/claims-carry-evidence.md), [record-dont-grade](skills/clear-mode/references/principles/record-dont-grade.md), [prove-on-the-real-artifact](skills/clear-mode/references/principles/prove-on-the-real-artifact.md), [ship-what-you-verified](skills/clear-mode/references/principles/ship-what-you-verified.md) |
| Comprehension | [model-the-domain](skills/clear-mode/references/principles/model-the-domain.md), [test-behavior](skills/clear-mode/references/principles/test-behavior.md), [minimize-reader-load](skills/clear-mode/references/principles/minimize-reader-load.md) |
| Maintenance | [less-code](skills/clear-mode/references/principles/less-code.md), [guards-over-reminders](skills/clear-mode/references/principles/guards-over-reminders.md), [budget-the-context](skills/clear-mode/references/principles/budget-the-context.md) |
| Repairability | [fix-at-the-right-layer](skills/clear-mode/references/principles/fix-at-the-right-layer.md), [fail-loudly-and-locally](skills/clear-mode/references/principles/fail-loudly-and-locally.md), [prefer-reversible-changes](skills/clear-mode/references/principles/prefer-reversible-changes.md) |
| Mutability | [experiment-before-asking](skills/clear-mode/references/principles/experiment-before-asking.md) |

## Playbooks

Each playbook in [`skills/clear-mode/references/playbooks/`](skills/clear-mode/references/playbooks/) gives the trigger, principles, steps, and stop conditions for a common task shape. Pick one when you start a run.

- **Investigate:** [investigate.md](skills/clear-mode/references/playbooks/investigate.md)
- **Bug-fix:** [bug-fix.md](skills/clear-mode/references/playbooks/bug-fix.md)
- **Feature:** [feature.md](skills/clear-mode/references/playbooks/feature.md)
- **Review:** [review.md](skills/clear-mode/references/playbooks/review.md)
- **Ship:** [ship.md](skills/ship/SKILL.md)
- **Pickup/handoff:** [pickup-handoff.md](skills/clear-mode/references/playbooks/pickup-handoff.md)

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

It binds to `127.0.0.1:8765` by default and reads `~/.local/state/clearstack/runs.jsonl` (or `$XDG_STATE_HOME/clearstack/runs.jsonl`). It makes no network requests and does not change the log. Pass `--host <address>` to bind elsewhere, for example a Tailscale address to reach it from another machine on your tailnet; the dashboard has no authentication, so only do this on a network you trust. This first version shows run status, duration, decision notes, and claims. `scripts/record end` reads token, cache, tool-call totals, and a per-tool-name call breakdown from the harness's own local session log (Claude Code's `~/.claude/projects/*/<session>.jsonl`, Codex's `~/.codex/sessions/**/<thread>.jsonl`, or Hermes's `~/.hermes/webui/sessions/<session>.json`) when a matching session id is set in the environment, and stores them on the run record. A run with no matching session log shows "not collected" rather than zero. The table and summary bar show per-run and total cost once any run in the log has telemetry, and a donut chart breaks tool calls down by name, both per run and aggregated across every run with telemetry.

The `/tokens` route shows a token-spend analytics view computed from `~/.hermes/state.db` on each request. It covers the last 14 days with headline totals, fresh input by model, a daily stacked bar chart, session-size buckets, surface breakdown, top sessions, tool-call volume, and fixed per-turn overhead from the system prompts table. A missing or unreadable state.db renders an empty-state note instead of a traceback.

The dashboard should also preserve the user's original request and pending decisions through long agent output, so the current goal does not get buried. This first version reads run records only and does not capture conversation text.

## Clear reflect

`clear-reflect` mines agent history for repeated waste and proposes guards, never applying them automatically. A weekly cron job runs the mining pass every Monday at 08:00 and delivers the human summary to the operator's chat.

```bash
# Run on demand
skills/clear-reflect/scripts/mine

# Pause the weekly job
hermes cron pause clear-reflect

# Resume
hermes cron resume clear-reflect
```

Run with `--format json` for machine-readable output, or `--format summary` for the human text only.

## Status

| | Piece | State |
|---|---|---|
| 1 | `clear-mode`, principles, `scripts/record` | merged |
| 1b | `clear-voice` output style and `voice-check` | merged |
| 1c | `clear-ci`: fail-fast CI watcher, `scripts/watch` | merged |
| 2 | Playbooks: investigate, bug-fix, feature, review, pickup/handoff | merged |
| 2b | Playbook: ship | merged |
| 3 | `clear-stats`: outcomes, claim vs proof, rework, corrections, and cost across Claude Code, Codex, Hermes, and GitHub | planned |
| 4 | `clear-reflect`: mine transcripts for repeated corrections and repeated tool-call chains, and propose principles, guards, or scripts | merged |
| 5 | Local dashboard: read-only view of run records | in progress; telemetry now reads from the harness session log when available |

## Develop

Link the skill from a checkout so edits take effect without reinstalling:

```bash
git clone https://github.com/aglowinthefield/clearstack ~/code/clearstack
ln -s ~/code/clearstack/skills/clear-mode ~/.agents/skills/clear-mode
python3 -m unittest discover -s tests
```

Claude Code reads `~/.claude/skills`, so link it there too. Everything is standard-library Python, including the logo: `python3 assets/make_logo.py` redraws `assets/logo.png`.

Enable the pre-commit hook so clear-voice violations are caught before they reach `main`:

```bash
git config core.hooksPath .githooks
```

## Credit

Inspired by [pstack](https://github.com/cursor/plugins/tree/main/pstack) by poteto.

## License

MIT
