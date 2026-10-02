# Budget the context

Pillar: maintenance

**Rule.** Context is a cost center. Keep the always-loaded prompt small, reset sessions at task boundaries, and carry state in records rather than in the transcript.

**Applies when.** Adding to a skill, writing a long run, or loading detail that only one step needs.

**Changes.** Move per-step detail into `references/` and load it at the step that needs it. Keep the always-loaded `SKILL.md` under roughly 6K chars. Start a new session for a new task rather than appending to an old transcript.

**Counter-example.** A skill whose `SKILL.md` loads every rule on every turn, doubling the prompt size for a one-line lookup.
