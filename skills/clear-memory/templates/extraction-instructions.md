Extract only facts that will still be true and useful in a future, unrelated conversation:
- lasting preferences about how the user wants agents to work, write, test, review, or ship
- standing decisions and rules (what is allowed, forbidden, or required going forward)
- stable environment facts: machines, accounts, usernames, hostnames, editors, tools, where things live

Do not extract:
- system or tool notifications, even when they appear in the user role: background process or job completions, exit codes, watch patterns, delegation or subagent results, heartbeats, emoji reactions, bracketed [IMPORTANT: ...], [System: ...], or out-of-band markers
- CI, check, build, deploy, or merge-queue results and timings
- what the user asked, requested, or wondered in this conversation, unless it states a lasting preference
- task, PR, ticket, card, or branch status, progress, counts, or plans ("is working on", "plans to", "is considering", "has N open PRs")
- one-off events and anything tied to today, tonight, or a specific date, unless the date is the fact
- approvals or answers that only make sense in context ("approved items 1 and 3", "option 2")
- credentials, tokens, passwords, or secret values

Write each memory as one present-tense sentence stating the rule or fact, not the incident that revealed it.
