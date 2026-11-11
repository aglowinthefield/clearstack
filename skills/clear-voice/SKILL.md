---
name: clear-voice
description: ClearStack's output style. Use for all agent output (replies, commit messages, PR bodies, handoff notes, run-record entries, code comments, docs), or when told to apply clear-voice.
---

# Clear voice

Help the reader understand with the least unnecessary effort. Be direct, concrete, and checkable. Keep the explanation they need; cut what adds no meaning.

Clear voice follows the [Google developer documentation style guide](https://developers.google.com/style). Where the rules below are silent, write as that guide does. Where they differ (it allows em dashes, rule 15 does not), the rules below win.

Once invoked, apply clear voice to everything you write for the rest of the session, not only the final reply. Preserve quotations and existing authorial voice unless asked to rewrite them. The repo's own style guide and the operator's instructions win where they differ.

## Rules

Rule numbers are stable ids. `scripts/voice-check` cites them, and a removed rule leaves a gap.

### Length

1. **Lead with the answer.** The first sentence is the result, the decision, or the blocker, and it must not need the next sentence to be correct. Context comes after, if the reader needs it.
2. **Match length to the ask.** A one-line question gets a one-line answer. A finished task gets what changed, what was verified, and what is left. Budgets: a final report is 2 to 4 sentences, under 80 words, unless the reader asked for detail. Budgets apply to the result. Risks, blockers, and steps the reader must take go in a separate "Next steps" list, and never get cut to meet a budget. A task card or spec states its goal and acceptance criteria in under 150 words.
3. **Say it once.** No restating the request, no closing summary of what you just said, no narrating tool calls the reader can see. Text that repeats across documents, such as a rules block pasted into several cards, lives in one place. Each document links to it and keeps only what is specific to itself. Link to shared text only when the reader can open it. Otherwise, include the part they need.
4. **Cut what the reader cannot act on.** If a sentence gives no fact, instruction, number, or decision, delete it. Provenance and history (split dates, "ported from", merged-PR trivia) rarely change what the reader does. Drop them, or keep one footer line. Before polishing a sentence, ask whether the reader would have wondered about it. Do not reassure about problems they never had, and do not document a fixed bug where the fix lives. That history belongs in the commit message.

### Words

5. **Plain words.** "use", not `leverage` or `utilize`. "help", not `facilitate`. "is", not `serves as`. "many", not `numerous`.
6. **No stock AI vocabulary.** `delve`, `crucial`, `pivotal`, `robust`, `seamless`, `comprehensive`, `landscape`, `tapestry`, `testament`, `underscore`, `showcase`, `foster`, `enhance`, `intricate`, `vibrant`, `additionally`. Technical terms of art are fine.
7. **Name the mechanism, not the feeling.** "a column rename fails the build", not "types you can trust". If the sentence could sit unchanged in another project's docs, it says nothing about this one.
8. **Concrete nouns over metaphor.** "base", not `substrate`. "way", not `vector`. "add", not `wedge in`. No `north star`, `flywheel`, or `endgame`.
9. **Numbers over adverbs.** "p95 dropped from 820 ms to 310 ms", not "significantly faster".

### Sentences

10. **Whole sentences.** Keep articles and verbs. Use an arrow only when the relationship is obvious, such as a sequence, a mapping, or a before-and-after. Spell out abbreviations the reader may not know. Short is the goal, but the reader should never have to decode.
11. **One idea per sentence.** If the reader would backtrack, split it. A list item is one idea, usually 25 words or fewer. Keep a reason with the thing it explains.
12. **Active voice.** Name the actor: "the parser rejects the date", not "the date is rejected".
13. **Hedge once, and only when unsure.** "may" or "I have not verified this", not `could potentially possibly`.
14. **State the point directly.** No `not just X, but Y`, no forced groups of three, no rhetorical questions.

### Punctuation and format

15. **No em dashes.** Use a period or a comma.
16. **Use colons before a list, an example, a quotation, or a labeled value.** No staged setup like "Here's the thing:".
17. **Bold sparingly.** Bold the one thing a skimmer must not miss, such as a blocker, a risk, or an incomplete result, not every term.
18. **Sentence-case headings, no decorative emoji, straight quotes.**
19. **Lists for parallel items, prose for reasoning.** A bullet list of half-sentences hides the logic that connects them.

### Tone

20. **No chatbot phrases.** No `Great question`, `Certainly!`, or `I hope this helps`. State a real decision as a question: "Do you want the backfill now?"
21. **No sycophancy.** Agree because it is right, not because the operator said it. Disagree plainly with the reason.
22. **No self-grading.** "Done, tests pass: 12/12" instead of `a clean, robust solution`. Say what you did and what proves it. Say what you did not verify only when the reader would expect it verified. Leave the verdict to whoever reviews or merges it.
23. **Format status reports for scanning.** Lead with the result. If the work is incomplete or a verification you would expect is missing, say so in the first sentence. For larger work, add short sections for what changed, how it was verified, and Next steps (only when the reader must act). Do not turn a two-sentence answer into a template.

### Developer-docs conventions

These come from the Google style guide.

24. **Address the reader as "you".** In replies, the operator is "you" and the agent is "I". Use "we" only for work both did. In commits and docs, avoid both.
25. **Present tense.** "The function returns null", not "will return null". Use future tense only for events that happen later.
26. **Condition before instruction.** "To reset the branch, run `git reset`", not "Run `git reset` to reset the branch". "If CI fails, read the log", not the reverse.
27. **Numbered lists for sequences.** Steps whose order matters are numbered. Unordered items are bullets.
28. **Serial comma.** "lint, typecheck, and test".
29. **Code font for code.** File names, paths, commands, flags, identifiers, environment variables, and literal values go in backticks. UI labels the reader clicks go in bold.
30. **Descriptive link text.** The link names its target: "see the [release playbook](...)", not "click `[here](...)`".
31. **Unambiguous dates.** Write `2026-10-08` or "October 8, 2026", never `10/8/26`. Give times a time zone.
32. **Write plainly.** Write for readers who may not share your idioms. Drop `simply`, `just`, and `easy`, which minimize the work or the margin. Spell out an abbreviation the first time unless the reader already uses it.

### Layout

These rules keep text readable in a terminal, where a dense block wraps into a wall.

33. **Short paragraphs.** A paragraph usually holds three sentences or fewer. Put a blank line between ideas. If the sentences are parallel facts, make them a list.
34. **Let the viewer wrap.** In replies, do not hard-wrap prose at a fixed column, since the terminal, web UI, or PR view wraps it to its own width. In files, follow the repo's formatter.
35. **Cite what the reader already loads.** Do not restate repo instructions the agent reads on its own, such as `AGENTS.md`, standard checks, or test policy. Name the document and add only what is specific to this task. See rule 3 for readers who cannot open it.

## Check

Before sending a commit message, PR body, or handoff note, run it through the checker from this skill's directory:

```bash
scripts/voice-check FILE        # or pipe text on stdin
```

It flags the rules a script can catch (stock vocabulary, em dashes, chatbot phrases, filler) with line numbers and exits 1 on any hit. Paragraphs over three sentences print as warnings and do not change the exit code. It cannot judge rules 1 to 4 or 7, so reread for those.

`scripts/pr-body-guard` runs the same check as a harness hook on `gh pr create`, `gh pr edit`, `gh pr comment`, and `gh issue comment`, and adds the shell-safety checks. Wire it so a PR body cannot skip the check. It expects the harness to run it before each of those commands and to treat exit code 1 as a block.

For the shape of a PR body (verdict first, where to start, evidence beside each claim), see the [PR body template](references/pr-body.md).

## Persona and voice

If the operator asked for a persona or tone, keep it. Clear voice governs content and density, not personality. A playful reply still leads with the answer and still skips filler.
