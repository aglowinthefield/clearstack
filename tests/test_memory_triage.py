import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "clear-memory" / "scripts"
TRIAGE = SCRIPTS / "triage"
WEEKLY = SCRIPTS / "weekly"

MEMORIES = [
    {"id": "durable", "memory": "Use fnm for Node versions; never nvm.", "created_at": "2026-10-01T00:00:00Z"},
    {"id": "event", "memory": "User's background process proc_abc1234567 completed normally with exit code 0", "created_at": "2026-10-02T00:00:00Z"},
    {"id": "request", "memory": "User asked whether the dashboard binds to localhost", "created_at": "2026-10-03T00:00:00Z"},
    {"id": "dated", "memory": "User is considering moving tracing to OpenTelemetry", "created_at": "2026-10-04T00:00:00Z"},
    {"id": "old-dup", "memory": "Deploys to staging run from the release workflow on main pushes", "created_at": "2026-09-01T00:00:00Z"},
    {"id": "new-dup", "memory": "Deploys to staging run from the release workflow on main pushes only", "created_at": "2026-10-05T00:00:00Z"},
    {"id": "secret", "memory": "Token is ghp_abcdefghijklmnopqrstuv for the bot", "created_at": "2026-10-06T00:00:00Z"},
    {"id": "vague", "memory": "User decided to proceed with option 2", "created_at": "2026-10-07T00:00:00Z"},
    {"id": "still-rule", "memory": "No notifications for failing checks while a PR is still a draft.", "created_at": "2026-10-09T00:00:00Z"},
    {"id": "short-fact", "memory": "User's channel ID is 1557049674131570759", "created_at": "2026-10-08T00:00:00Z"},
]


def run(*args, stdin=None):
    return subprocess.run([str(TRIAGE), *args], input=stdin, capture_output=True, text=True)


class TriageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ledger = str(self.tmp / "ledger.jsonl")

    def scan(self, data, *extra):
        result = run("scan", "-", "--ledger", self.ledger, *extra, stdin=json.dumps(data))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def by_id(self, report):
        return {m["id"]: m for m in report["queue"]}

    def test_each_rule_flags_its_memory_and_durable_facts_stay_out(self):
        queue = self.by_id(self.scan({"results": MEMORIES}))
        self.assertEqual(queue["event"]["rules"], [1])
        self.assertEqual(queue["request"]["rules"], [2])
        self.assertEqual(queue["dated"]["rules"], [3])
        self.assertEqual(queue["old-dup"]["duplicate_of"], "new-dup")
        self.assertIn(5, queue["secret"]["rules"])
        self.assertEqual(queue["vague"]["rules"], [6])
        for kept in ("durable", "new-dup", "short-fact", "still-rule"):
            self.assertNotIn(kept, queue)

    def test_suggestions_and_order_put_deletions_first(self):
        report = self.scan(MEMORIES)
        self.assertEqual(report["queue"][0]["suggest"], "delete")
        self.assertEqual(self.by_id(report)["dated"]["suggest"], "verify")
        self.assertEqual(self.by_id(report)["vague"]["suggest"], "update")

    def test_all_queues_unflagged_memories_as_keep(self):
        queue = self.by_id(self.scan(MEMORIES, "--all"))
        self.assertEqual(queue["durable"]["suggest"], "keep")

    def test_jsonl_input_is_accepted(self):
        jsonl = "\n".join(json.dumps(m) for m in MEMORIES)
        result = run("scan", "-", "--ledger", self.ledger, stdin=jsonl)
        self.assertEqual(json.loads(result.stdout)["total"], len(MEMORIES))

    def test_decided_memories_leave_the_queue_until_their_text_changes(self):
        run("decide", "dated", "keep", "--old", MEMORIES[3]["memory"], "--ledger", self.ledger)
        run("decide", "event", "delete", "--ledger", self.ledger)
        report = self.scan(MEMORIES)
        self.assertEqual(report["already_reviewed"], 2)
        self.assertNotIn("dated", self.by_id(report))
        edited = [dict(m, memory="User is considering Grafana now") if m["id"] == "dated" else m for m in MEMORIES]
        self.assertIn("dated", self.by_id(self.scan(edited)))

    def test_skip_keeps_a_memory_queued(self):
        run("decide", "vague", "skip", "--ledger", self.ledger)
        self.assertIn("vague", self.by_id(self.scan(MEMORIES)))

    def test_update_requires_new_text(self):
        result = run("decide", "vague", "update", "--ledger", self.ledger)
        self.assertEqual(result.returncode, 2)

    def test_from_markdown_splits_section_sign_blocks(self):
        md = self.tmp / "MEMORY.md"
        md.write_text("First fact.\n\u00a7\nSecond fact\nspans lines.\n")
        result = run("from-markdown", str(md))
        entries = json.loads(result.stdout)
        self.assertEqual([e["text"] for e in entries], ["First fact.", "Second fact\nspans lines."])
        self.assertTrue(all(e["id"] for e in entries))


class WeeklyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ledger = str(self.tmp / "ledger.jsonl")

    def weekly(self, records, *extra):
        export = self.tmp / "export.json"
        export.write_text(json.dumps(records))
        return subprocess.run(
            [str(WEEKLY), "--export-cmd", f"cat {export}", "--ledger", self.ledger, *extra],
            capture_output=True, text=True,
        )

    def test_reports_flag_counts_and_samples(self):
        result = self.weekly(MEMORIES, "--samples", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertTrue(lines[0].startswith("Memory check: 6 of 10 memories flagged"), lines[0])
        self.assertEqual(sum(line.startswith("- [") for line in lines), 2)
        self.assertIn("...and 4 more", result.stdout)

    def test_clean_store_prints_one_line(self):
        result = self.weekly([MEMORIES[0]])
        self.assertEqual(result.stdout, "Memory check: 1 memories, nothing flagged.\n")

    def test_export_failure_exits_nonzero_with_reason(self):
        result = subprocess.run([str(WEEKLY), "--export-cmd", "false"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("export failed", result.stderr)


if __name__ == "__main__":
    unittest.main()
