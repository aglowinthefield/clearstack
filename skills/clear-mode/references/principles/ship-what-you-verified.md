# Ship what you verified

Pillar: observation

**Rule.** The artifact you verified must be the artifact that ships. Prove the fix is in the commit being shipped and that the build under test was cut from that commit.

**Applies when.** Handing a build, branch, or deploy to anyone else, or verifying a build you did not cut.

**Changes.** You check the commit SHA inside the artifact (a build number, a version endpoint, `git merge-base --is-ancestor`) before calling it verified. A rebuilt or re-squashed commit needs verifying again.

**Counter-example.** A build cut from a branch that was missing the fix it was cut for, sent to testers because the fix passed locally.
