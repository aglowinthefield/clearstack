# Test behavior

Pillar: comprehension

**Rule.** Call the code the way its users do and assert what they observe against a literal expected value. A test is also documentation of what the code promises.

**Applies when.** Writing, changing, or keeping a test.

**Changes.** Tests go through the public entry point and assert outputs, not calls to internal helpers. If a test would still pass with every imported function returning `undefined`, rewrite the assertion or delete the test. Use [`test-audit`](../../../test-audit/SKILL.md) before adding, changing, reviewing, or sweeping tests.

**Counter-example.** A test that mocks the database, calls the handler, and asserts the mock was called once, which passes no matter what the query says.
