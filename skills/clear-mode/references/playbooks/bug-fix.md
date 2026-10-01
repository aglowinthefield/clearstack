# Bug-fix

Trigger: a specific, reproducible failure needs a code change.

## Principles

- `fix-at-the-right-layer`
- `fail-loudly-and-locally`
- `prove-on-the-real-artifact`
- `test-behavior`
- `less-code`

## Steps

1. Open a run record with `--playbook bug-fix`.
2. Write or find a test that fails on the current code.
3. Change the smallest layer that fixes the test. Do not add an abstraction for a single case.
4. Run the test and any related tests.
5. Run the full test suite or the subset the repo checks.
6. End the record with verified claims.

## Stop conditions

- The fix is committed and tests pass.
- The fix breaks an unrelated test.
- Two fixes that share one premise have failed the same check.