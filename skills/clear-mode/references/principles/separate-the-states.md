# Separate the states

Pillar: observation

**Rule.** "Changed locally", "committed", "pushed", "merged", "in a build", "verified" and "approved" are different facts. Report each one separately and never let one stand in for another.

**Applies when.** Reporting status, writing a PR body, or ending a run.

**Changes.** A report names the branch and commit the work sits on, what has been verified on which artifact, and what still waits on a human. "Fixed" alone is not a status.

**Counter-example.** "The crash is fixed" when the fix is uncommitted in a worktree and the build testers have does not contain it.
