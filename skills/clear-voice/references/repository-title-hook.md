# Repository title checks

The PR-command guard delegates title validation to repositories that provide `.agents/hooks/pr-title.py` at their Git root.
Repositories without that adapter keep the existing body checks.

## Adapter protocol

Before running `gh pr create` or `gh pr edit`, the guard sends the adapter JSON on stdin:

```json
{"argv": ["pr", "create", "--title", "test(admin): fix the lock drill"], "cwd": "/checkout"}
```

The adapter returns a JSON list of block reasons.
An empty list passes; a nonempty list blocks with those reasons.
A subprocess error, timeout, or malformed reply blocks publication.

## Policy ownership

The repository owns its type and scope rules.
Read its declared policy instead of keeping a list in the global guard.
The adapter decides whether an edit changes the title and can leave body-only edits alone.

Run the guard only in trusted checkouts, because the adapter is repository code.
This preflight protects guarded agent commands, not commands from an unguarded terminal.
Keep the repository's CI title check enabled.
