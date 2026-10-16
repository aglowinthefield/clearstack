---
name: clear-memory
description: Use when reviewing an agent's saved memories for accuracy. Flags stale, duplicate and one-off entries, asks the operator about each, then fixes them in any memory provider.
---

# Clear memory

Saved memories go stale. A preference changes, a rule is lifted, a status line ("PR 412 is failing") stays true for an hour and is injected for months. `clear-memory` runs an interactive review: a script flags suspect entries, the agent checks them against current sources, the operator decides, and the agent applies each decision through whatever memory provider holds them.

It is provider-agnostic. The script reads a plain JSON export and never calls a provider. The agent does the export and the writes with the provider's own tools.

## Flags

`scripts/triage scan` marks each memory with zero or more numbered flags and a suggested action:

1. **event** (suggest delete): a one-off log of something that happened, like a background process finishing or a check timing out.
2. **request** (suggest delete): records what the operator asked for instead of what is true. Keep it only when the request states a lasting preference.
3. **time-bound** (suggest verify): status that expires, such as "currently", "is considering", "plans to", or a dated count.
4. **duplicate** (suggest delete): a near-duplicate of a newer memory, named in `duplicate_of`.
5. **secret** (suggest delete): looks like a credential. Delete it even if the operator wants the fact kept, and save the fact without the value.
6. **vague** (suggest update): points at context the memory does not carry, like "item (2)" or "option 3".

Unflagged memories are not proven true. `--all` queues them too, as `keep` suggestions.

## Procedure

1. **Export.** Write every memory to one JSON or JSONL file in a scratch directory, never in a repo. `references/providers.md` covers mem0, file-based memories such as Hermes `MEMORY.md`, and any other provider. Done when the file's record count matches the provider's own count.
2. **Scan.** From this skill's directory run `scripts/triage scan <export> --format summary`, then `scripts/triage scan <export> > queue.json`. Tell the operator the totals per flag before asking anything.
3. **Check before asking.** For each queued memory that makes a checkable claim (a config value, a repo rule, a tool's behavior, a PR or ticket state), check it against the source of truth first: the file, `git`, the tracker, or the config. Put the evidence in the question. Do not ask the operator to remember what a command can tell you.
4. **Ask in batches.** Use the harness's question tool: `clarify` in Hermes, `AskUserQuestion` in Claude Code, otherwise a numbered list in the reply. For each memory, show its text, flags and evidence, and offer `Keep`, `Delete`, and `Update to: <proposed text>` with the suggested action first. Ask up to four or five memories per call. When the answer is a subset ("which of these to keep"), use a multi-select or a free-text question; never offer a choice like "tell me which" that leaves nowhere to type the answer.
5. **Bulk-confirm the obvious groups.** Flags 1 and 4 are often hundreds of entries. Show a count and five samples and ask once whether to delete the whole group. Any entry the operator pulls out goes back to the one-by-one queue.
6. **Apply and record.** Apply each answer with the provider's tools right away, then record it: `scripts/triage decide <id> <keep|update|delete|skip> [--text NEW] [--old CURRENT]`. Pass `--old` on keep so an edit to that memory later puts it back in the queue. Never delete or rewrite a memory the operator has not answered for.
7. **Resume.** The ledger (`$XDG_STATE_HOME/clearstack/memory-review.jsonl`, or `--ledger`) skips decided memories on the next scan. Stop when the operator says so or the queue is empty, and report: reviewed, kept, updated, deleted, still queued.
8. **Tighten the writer.** A review only clears the backlog; the next week of turns refills it unless the source changes. Find what wrote the junk: explicit saves by the agent, or a provider that extracts facts from every turn automatically. For automatic extraction, set the provider's extraction instructions from `templates/extraction-instructions.md`, then prove them on a throwaway user id: send a few junk turns and one real preference, confirm only the preference is stored, and delete the test memories. Tell the operator which writer was the source and what changed.

## Writing a replacement

An updated memory states one lasting fact in present tense, with no date unless the date is the fact. Prefer the rule over the incident: "Stacked PRs are allowed (since #3988)", not "On Tuesday the user asked to stack a PR". If no lasting fact remains, delete instead of rewording.

## Use

```bash
scripts/triage scan export.jsonl --format summary
scripts/triage scan export.jsonl --limit 20 > queue.json
scripts/triage decide 637dd4bb update --text "Stacked PRs are allowed."
scripts/triage from-markdown ~/.hermes/memories/MEMORY.md > memory.json
```

Standard-library Python. The script makes no network calls and never changes a provider.

## Scheduled check

`scripts/weekly` exports, scans and prints a short report for a no-agent cron job to deliver: the flagged count by flag, a few samples, and a prompt to start a review. It is read-only and never changes a memory.

```bash
scripts/weekly --provider mem0 --env-file ~/.hermes/.env --user-id <id>
scripts/weekly --export-cmd "<command that prints JSON or JSONL>"
```

`scripts/export-mem0` is the mem0 adapter. Other providers plug in through `--export-cmd`.
