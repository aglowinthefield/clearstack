# Prefer reversible changes

Pillar: repairability

**Rule.** Shape changes so they can be undone cheaply: small PRs, migrations that roll back, unfinished behavior behind a flag, one concern per commit.

**Applies when.** Planning a change that touches data, a public contract, or more than one PR.

**Changes.** You split work into units that each leave the system working, and put anything irreversible (a destructive migration, a deleted endpoint) in its own step after the reversible part has shipped.

**Counter-example.** One PR that renames a column, rewrites its readers, and drops the old column, so reverting it loses data.
