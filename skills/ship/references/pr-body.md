# PR body

A PR body is read by someone deciding whether to merge, and later by someone asking why a line exists. Write it so both can skip to what they need.

Copy this file to a repo's `.github/pull_request_template.md`, or write the body from it directly. Delete any section that would be empty.

`clear-voice` governs the prose: paragraphs of three sentences at most, plain words, no em dashes. Run `scripts/voice-check` on the body before posting, and wire `scripts/pr-body-guard` so a body cannot skip it.

## Shape

Each technique below trades a paragraph for something a reader can skip or expand.

- **Verdict first.** The first line, before any heading, says what the PR does and what a user or operator notices. A reader who stops there knows what merged.
- **Where to start.** Name the one file to read first and the one hunk that needs judgment. Label the rest as mechanical: tests, docs, renames.
- **Permalinks over descriptions.** A GitHub permalink with the commit SHA and `#L10-L20` renders the lines inline. Point at the key change instead of describing it.
- **Evidence beside each claim.** The test name and count, the command and its exit code, or the CI run link, on the same line as the claim it proves.
- **Collapsed evidence.** Test output, log tails, and screenshots go in `<details>` with a one-line `<summary>`. The claim stays visible and the proof is one click away.
- **Tables for comparisons.** Before and after, option A against option B, file against reason.
- **A Mermaid diagram for a flow or state machine.** GitHub renders a ```` ```mermaid ```` fence. Five boxes beat a paragraph when the change is a pipeline. Quote every label, `A["like this"]`, since parentheses and brackets inside an unquoted label are shape syntax and fail to render.
- **Checkboxes for open decisions.** `- [ ]` gives the operator something to tick instead of a question buried in prose.

## Template

```markdown
One sentence: what this PR does and what a user or operator notices.

## Where to start

- Read `path/to/file` first. The hunk that needs judgment: <permalink with SHA and line range>.
- The rest is mechanical: tests, docs, renames.

## Changes

- One line per change, grouped by behavior.

## Verification

- Verified: <claim>. <evidence: test name and count, command and exit code, or CI link>
- Not verified: <claim>. <why you could not prove it>

<details><summary>Test output</summary>

~~~
paste the output here, inside a fence so it is not read as prose
~~~

</details>

## Behavior changes

| Before | After |
|---|---|
| <what happened> | <what happens now> |

## Not in this PR

- Known gaps and follow-ups, so the reviewer does not flag them.

## Rollback

One line: revert the commit, unset the hook, or run the down migration.

## Decisions

- [ ] A question only the operator can answer.
```
