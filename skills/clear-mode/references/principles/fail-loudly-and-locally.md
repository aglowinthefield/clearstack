# Fail loudly and locally

Pillar: repairability

**Rule.** When something breaks, the error names what broke and where, as close to the cause as possible. No silent fallbacks, no catch-and-continue, no default value that hides a missing one.

**Applies when.** Writing error handling, parsing external input, or adding a fallback.

**Changes.** You validate at the boundary and throw with the offending value in the message. A fallback is allowed only when the fallback behavior is correct for users, and it is logged.

**Counter-example.** `catch {}` around a network call so the screen renders empty, and the bug report says "feed is blank sometimes" with nothing in the logs.
