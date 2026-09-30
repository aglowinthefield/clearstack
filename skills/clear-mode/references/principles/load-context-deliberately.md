# Load context deliberately

Pillar: context

**Rule.** Read the source of truth first, read docs at the step that needs them, and send bulk reading to a read-only subagent that returns a summary.

**Applies when.** Starting a task, entering an unfamiliar area, or about to read many files or a large log.

**Changes.** Current source beats historical docs, so you locate the code before reading the prose about it. A 5,000-line log goes to a subagent with a question, and only its answer enters your context.

**Counter-example.** Reading every doc under `docs/` at turn start, then running out of room before reading the function that owns the bug.
