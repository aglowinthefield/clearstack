# Prove on the real artifact

Pillar: observation

**Rule.** Verify on the thing users touch: the running app, the real device, the rendered page, the value actually read back. A passing unit test, a green build, or a screenshot from a simulator proves only itself.

**Applies when.** About to declare a change done.

**Changes.** You run the feature on the target surface and read the result. When you cannot reach that surface, the claim goes in `--unverified` with the surface named.

**Counter-example.** Declaring a layout fix done from an iOS simulator screenshot when the bug report came from an Android phone.
