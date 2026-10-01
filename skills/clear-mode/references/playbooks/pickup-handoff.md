# Pickup and handoff

Trigger: a parked run record or a handoff note needs to be resumed.

## Principles

- `load-context-deliberately`
- `leave-context-behind`
- `separate-the-states`
- `experiment-before-asking`

## Steps

1. Open a run record with `--playbook pickup-handoff`. Set `--parent-run` if this continues a subagent run.
2. Read the parked record, the handoff note, and the branch state.
3. Verify each claim the previous run marked as verified. Re-verify on the current artifact.
4. Do the next reversible step. Commit at each unit.
5. If the handoff names a single decision, resolve it or park with the new state.
6. End the record with verified claims for everything you proved.

## Stop conditions

- The work is done and verified.
- The handoff is missing a claim you need to proceed.
- The next step is irreversible and nobody has granted it.