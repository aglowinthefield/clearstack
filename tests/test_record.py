import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RECORD = Path(__file__).resolve().parent.parent / "skills" / "clear-mode" / "scripts" / "record"


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.TemporaryDirectory()
        self.env = {**os.environ, "XDG_STATE_HOME": self.state.name}

    def tearDown(self):
        self.state.cleanup()

    def run_record(self, *args):
        return subprocess.run([str(RECORD), *args], env=self.env, capture_output=True, text=True)

    def log(self):
        path = Path(self.state.name) / "clearstack" / "runs.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_a_run_writes_start_note_and_end_under_one_id(self):
        run_id = self.run_record("start", "--task", "fix scroll drift", "--playbook", "bug-fix").stdout.strip()
        self.run_record("note", run_id, "fixed in the hook, not the three callers")
        self.run_record("end", run_id, "--status", "done", "--verified", "drift gone: 0px over 60s trace")

        log = self.log()
        self.assertEqual([e["event"] for e in log], ["start", "note", "end"])
        self.assertEqual({e["run"] for e in log}, {run_id})
        self.assertEqual(log[0]["task"], "fix scroll drift")
        self.assertEqual(log[2]["verified"], ["drift gone: 0px over 60s trace"])

    def test_unknown_run_is_refused(self):
        result = self.run_record("end", "cr-19700101-000000", "--status", "done")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no run", result.stderr)

    def test_parked_run_must_name_the_decision_it_needs(self):
        run_id = self.run_record("start", "--task", "migrate store").stdout.strip()
        result = self.run_record("end", run_id, "--status", "parked")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([e["event"] for e in self.log()], ["start"])


if __name__ == "__main__":
    unittest.main()
