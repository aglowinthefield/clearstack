# Guards over reminders

Pillar: maintenance

**Rule.** Fix a mistake at the strongest level that holds, in this order: make it impossible (a type, a shared contract, deleting the path), make CI or a lint rule catch it, write it down. Relying on someone remembering is not a control.

**Applies when.** Something went wrong, or you catch yourself writing the same instruction a second time.

**Changes.** The fix for a repeated mistake is a test, a check, or a type, and the note in a doc is the fallback when no guard is possible. If a check exists, the doc names it instead of restating it.

**Counter-example.** Adding "remember to run the migration test" to a README after a broken migration shipped, when CI could run it.
