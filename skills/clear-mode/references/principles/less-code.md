# Less code

Pillar: maintenance

**Rule.** Prefer the change that leaves less to maintain: reuse an existing seam, delete dead and superseded paths, and add no option, mode, or extension point the task does not need. Less means fewer concepts, not fewer lines.

**Applies when.** Sizing a change, adding a file, dependency, flag, or abstraction.

**Changes.** Every new file, dependency, or option needs a reason you can state. You remove what the change makes obsolete in the same diff. A diff that removes more than it adds is a good sign.

**Counter-example.** Adding a config flag "in case someone needs the old behavior" that nobody ever sets.
