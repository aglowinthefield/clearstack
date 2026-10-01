# Investigate

Trigger: a symptom, error, or behavior needs explanation before a fix can be planned.

## Principles

- `load-context-deliberately`
- `experiment-before-asking`
- `claims-carry-evidence`
- `separate-the-states`

## Steps

1. Open a run record with `--playbook investigate`.
2. Record the symptom exactly: error text, log line, or observed behavior.
3. Reproduce it on the real artifact. A local build, a test, or a script that shows the same output is evidence.
4. Read only the code the symptom touches. Stop at the layer that explains the behavior.
5. State the cause as a claim with evidence, not as a guess.
6. If the cause is clear, move to bug-fix or feature. If not, park the run with the open question.

## Stop conditions

- The cause is found and reproducible.
- Two experiments that share one premise have failed.
- The next step needs access you do not have.