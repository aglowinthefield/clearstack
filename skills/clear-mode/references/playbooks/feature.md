# Feature

Trigger: new behavior is needed and the interface is not yet fixed.

## Principles

- `model-the-domain`
- `experiment-before-asking`
- `prefer-reversible-changes`
- `minimize-reader-load`
- `test-behavior`

## Steps

1. Open a run record with `--playbook feature`.
2. Read the interface or schema the feature touches. State the contract in a note.
3. Write a test that describes the new behavior before the implementation.
4. Build the smallest implementation that passes the test.
5. Run the test suite.
6. End the record with verified claims.

## Stop conditions

- The feature is committed and tests pass.
- A product or preference call remains that no experiment can settle.
- The change would alter a public contract without a plan for migration.