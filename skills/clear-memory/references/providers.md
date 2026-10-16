# Memory providers

How to export, update and delete memories in the providers seen so far. For any other provider, produce JSON records with an `id` and the memory text, then apply decisions with that provider's own update and delete calls.

Keep exports in a scratch directory. They hold personal data and must not be committed.

## mem0 (platform API)

The search tools return at most a few dozen results, so export through the REST list endpoint. It pages at up to 100 per request and reports a total `count`:

```bash
p=1; : > mem0.jsonl
while :; do
  r=$(curl -s "https://api.mem0.ai/v1/memories/?user_id=$MEM0_USER&page=$p&page_size=100" \
    -H "Authorization: Token $MEM0_API_KEY")
  echo "$r" | jq -c '.results[] | {id, memory, created_at, updated_at}' >> mem0.jsonl
  [ "$(echo "$r" | jq -r .next)" = null ] && break
  p=$((p+1))
done
```

Apply decisions with the harness's mem0 tools (`mem0_update`, `mem0_delete`) when they exist. Otherwise use `PUT` with `{"text": ...}` or `DELETE` on `https://api.mem0.ai/v1/memories/<id>/`.

## File-based memories (Hermes built-in, plain Markdown)

Hermes keeps its built-in memory in `~/.hermes/memories/MEMORY.md` and `USER.md`, one entry per block separated by a line holding `§`. Convert with:

```bash
scripts/triage from-markdown ~/.hermes/memories/MEMORY.md > memory.json
```

Ids are content hashes, so an edited entry gets a new id. Apply decisions through the harness's memory tool (Hermes: `memory` with `replace` or `remove`, matching by a unique substring), not by editing the file while a session holds its lock.

## Claude Code

Claude Code memory is plain Markdown (`CLAUDE.md`, `~/.claude/CLAUDE.md`, and any auto-memory files it keeps). Export one entry per bullet or paragraph as JSON records, then apply decisions with edits to those files.
