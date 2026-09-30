# Model the domain

Pillar: comprehension

**Rule.** Name the data shape before writing logic, and encode the domain in a structure (a type, a table, a state machine) instead of conditionals scattered across files.

**Applies when.** Writing stateful logic, adding a branch on a kind or status, or repeating one assumption about a shape in several places.

**Changes.** You write the type or table first and let the code follow from it. A new case becomes one row or one variant, and the compiler finds every site that must handle it.

**Counter-example.** `if (kind === "blog")` checks spread across nine files, so adding a kind means finding them all by search.
