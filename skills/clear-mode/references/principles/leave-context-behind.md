# Leave context behind

Pillar: context

**Rule.** Every run leaves the next reader, human or agent, what they need to continue without asking you: why the change exists, what was decided and rejected, and where the work stopped.

**Applies when.** You make a non-obvious decision, stop before done, or change code whose reason is not visible in the diff.

**Changes.** The reason goes where the next reader will look: a `record note` for the decision trail, the commit message for the change, a code comment only for a constraint the code cannot state. A parked run ends with a handoff note, not a transcript to reread.

**Counter-example.** A PR titled "fix feed" whose body lists the files touched. The reviewer has to reverse-engineer which bug it fixes and why this layer was chosen.
