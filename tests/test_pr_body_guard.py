import json
import subprocess
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent.parent / "skills" / "clear-voice" / "scripts" / "pr-body-guard"
PR = "gh pr create --title t"


class PrBodyGuardTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "clean.md").write_text("Fixes the parser.\n")
        (self.dir / "dirty.md").write_text("We leverage a cache.\n")

    def run_guard(self, command):
        payload = json.dumps({"tool_input": {"command": command}, "cwd": str(self.dir)})
        return subprocess.run([str(GUARD)], input=payload, capture_output=True, text=True)

    def assert_allowed(self, command):
        result = self.run_guard(command)
        self.assertEqual(result.returncode, 0, f"{command!r}: {result.stderr}")

    def assert_blocked(self, command, reason):
        result = self.run_guard(command)
        self.assertEqual(result.returncode, 2, f"{command!r} was allowed")
        self.assertIn(reason, result.stderr)
        self.assertEqual(json.loads(result.stdout)["decision"], "block")

    def test_commands_that_post_no_body_pass(self):
        for command in (
            "git status",
            "gh pr view 12",
            "gh pr merge 12",
            "gh pr edit 12 --add-label perf",
            f"{PR}",
            "gh api repos/o/r/pulls/12 -f body='We leverage it'",
            "echo \"gh pr create --fill\"",
            "grep -n 'gh pr create --body' foo.sh",
        ):
            with self.subTest(command):
                self.assert_allowed(command)

    def test_clean_bodies_pass_wherever_the_command_puts_them(self):
        for command in (
            f"{PR} --body 'Fixes the parser.'",
            f"{PR} --body='Fixes the parser.'",
            f"{PR} --body-file clean.md",
            f"gh pr edit 12 -F {self.dir}/clean.md",
            f"{PR} --body-file - <<'EOF'\nUses `my_var` and $HOME.\nEOF",
            f"{PR} --body \"$(cat <<'EOF'\nFixes the parser.\nEOF\n)\"",
            f"cd {self.dir} && {PR} --body-file clean.md",
            f"sh -c \"{PR} --body 'Fixes the parser.'\"",
            f"url=$({PR} --body 'Fixes the parser.')",
            "gh issue comment 9 --body-file clean.md",
            "gh pr comment 12 --body 'Fixes the parser.'",
        ):
            with self.subTest(command):
                self.assert_allowed(command)

    def test_style_breaks_in_the_body_block_with_line_and_rule(self):
        for command in (
            f"{PR} --body 'We leverage a cache.'",
            f"{PR} -b 'We leverage a cache.'",
            "gh pr edit 12 --body-file dirty.md",
            f"{PR} --body-file - <<'EOF'\nWe leverage a cache.\nEOF",
            f"{PR} --body \"$(cat <<'EOF'\nWe leverage a cache.\nEOF\n)\"",
            f"env -u X Y=1 {PR} --body 'We leverage a cache.'",
            f"/usr/bin/{PR} --body 'We leverage a cache.'",
            f"git push && {PR} --body 'We leverage a cache.'",
            f"bash -lc \"cd /x && {PR} --body 'We leverage a cache.'\"",
            f"eval '{PR} --body \"We leverage a cache.\"'",
            f"echo \"$({PR} --body 'We leverage a cache.')\"",
            "gh pr comment 12 --body-file dirty.md",
            "gh issue comment 9 -b 'We leverage a cache.'",
        ):
            with self.subTest(command):
                self.assert_blocked(command, "body line 1: rule 5")

    def test_bodies_the_guard_cannot_read_block(self):
        for command, reason in (
            (f"{PR} --fill", "--fill and --template"),
            (f"{PR} --fill-first", "--fill and --template"),
            (f"{PR} -T bug.md", "--fill and --template"),
            ("gh pr edit 12 -F -", "reads stdin"),
            ("gh pr edit 12 --body-file missing.md", "cannot read missing.md"),
        ):
            with self.subTest(command):
                self.assert_blocked(command, reason)

    def test_bodies_the_shell_would_rewrite_block(self):
        for command in (
            f"{PR} --body \"Adds `x`.\"",
            f"{PR} --body \"$BODY\"",
            f"{PR} --body \"$(cat clean.md)\"",
            f"{PR} --body-file - <<EOF\nAdds `x`.\nEOF",
        ):
            with self.subTest(command):
                self.assert_blocked(command, "expand")

    def test_leaked_shell_syntax_in_a_file_blocks(self):
        (self.dir / "leak.md").write_text("$(cat <<EOF\nDone.\nEOF\n")
        self.assert_blocked("gh pr edit 12 --body-file leak.md", "shell syntax leaked")

    def test_prose_that_mentions_leaked_syntax_passes(self):
        (self.dir / "doc.md").write_text("The guard blocks `$(cat <<` and a bare `EOF` line.\n")
        self.assert_allowed("gh pr edit 12 --body-file doc.md")

    def test_old_humanized_marker_does_not_bypass(self):
        self.assert_blocked(f"HERMES_HUMANIZED=1 {PR} --body 'We leverage it.'", "rule 5")

    def install_title_adapter(self):
        subprocess.run(["git", "init", str(self.dir)], check=True, capture_output=True)
        adapter = self.dir / ".agents/hooks/pr-title.py"
        adapter.parent.mkdir(parents=True)
        # Exercise the adapter subprocess protocol without coupling the guard
        # tests to any one repository's title vocabulary.
        adapter.write_text(
            "import json, sys\n"
            "payload = json.load(sys.stdin)\n"
            "assert payload['argv'][:2] in (['pr', 'create'], ['pr', 'edit'])\n"
            "print(json.dumps(['repo title rejected'] if '--title=bad' in payload['argv'] else []))\n"
        )
        return adapter

    def test_repository_adapter_checks_create_and_edit_through_shell_wrappers(self):
        self.install_title_adapter()
        for command in (
            "gh pr create --title=bad",
            "gh pr edit 12 --title=bad",
            "env X=1 gh pr create --title=bad",
            "bash -lc 'gh pr edit 12 --title=bad'",
            "echo $(gh pr create --title=bad)",
            f"cd {self.dir} && gh pr create --title=bad",
        ):
            with self.subTest(command):
                self.assert_blocked(command, "repo title rejected")
        self.assert_allowed("gh pr create --title=good --body-file clean.md")
        self.assert_allowed("gh pr edit 12 --body-file clean.md")
        self.assert_allowed("echo 'gh pr create --title=bad'")
        self.assert_allowed("gh pr comment 12 --body-file clean.md")

    def test_repository_adapter_discovery_uses_tool_workdir_and_subdirectories(self):
        self.install_title_adapter()
        nested = self.dir / "nested"
        nested.mkdir()
        payload = {"cwd": "/", "tool_input": {
            "command": "gh pr create --title=bad", "workdir": str(nested),
        }}
        result = subprocess.run([str(GUARD)], input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("repo title rejected", result.stderr)

    def test_broken_opted_in_adapter_blocks_publication(self):
        adapter = self.install_title_adapter()
        for source in ("raise RuntimeError('broken adapter')", "print('not json')", "print('{}')"):
            adapter.write_text(source)
            self.assert_blocked("gh pr create --title=good", "title hook")

    def test_unparseable_input_is_not_blocked(self):
        for stdin in ("", "not json", json.dumps({"tool_input": {}}), json.dumps({"tool_input": {"command": "gh 'x"}})):
            with self.subTest(stdin):
                result = subprocess.run([str(GUARD)], input=stdin, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
