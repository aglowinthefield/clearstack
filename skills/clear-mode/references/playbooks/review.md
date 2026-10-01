# Review

Trigger: a diff, PR, or change needs judgment before it merges.

## Principles

- `separate-the-states`
- `claims-carry-evidence`
- `record-dont-grade`
- `minimize-reader-load`
- `less-code`
- `guards-over-reminders`

## Steps

1. Open a run record with `--playbook review`.
2. Read the diff and the linked issue or context.
3. Judge the change against the six pillars:
   - **Context:** does the next reader have what they need to act?
   - **Observation:** are claims backed with evidence?
   - **Comprehension:** can a reader follow the logic and the naming?
   - **Maintenance:** is there less code than before, or a good reason for more?
   - **Repairability:** does the change fail loudly and locally when it breaks?
   - **Mutability:** can it be changed without fear?
4. Write each finding as a concrete issue: file, line, problem, fix.
5. End the record with a verdict and any unverified claims.

## Stop conditions

- The review is complete and findings are recorded.
- The reviewer lacks context to judge a part of the change.
- The review finds a security or safety issue that needs immediate escalation.