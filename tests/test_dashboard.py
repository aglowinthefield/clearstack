import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clearstack.dashboard import default_log_path, load_runs, render_page


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.log = Path(self.temp.name) / "runs.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def write_events(self, *events):
        self.log.write_text("".join(json.dumps(event) + "\n" for event in events))

    def test_empty_xdg_state_home_uses_default_state_directory(self):
        home = Path(self.temp.name) / "home"
        with patch.dict("os.environ", {"XDG_STATE_HOME": ""}), patch("clearstack.dashboard.Path.home", return_value=home):
            self.assertEqual(default_log_path(), home / ".local" / "state" / "clearstack" / "runs.jsonl")

    def test_groups_events_by_run_and_sorts_newest_first(self):
        self.write_events(
            {"ts": "2026-09-30T10:00:00+00:00", "event": "start", "run": "older", "task": "old task", "agent": "codex"},
            {"ts": "2026-09-30T10:01:00+00:00", "event": "note", "run": "older", "text": "decision"},
            {"ts": "2026-09-30T10:05:00+00:00", "event": "end", "run": "older", "status": "done", "verified": ["tests pass"], "unverified": []},
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "newer", "task": "new task", "agent": "hermes"},
        )

        runs = load_runs(self.log)

        self.assertEqual([run["id"] for run in runs], ["newer", "older"])
        self.assertEqual(runs[0]["status"], "open")
        self.assertEqual(runs[1]["status"], "done")
        self.assertEqual([event["event"] for event in runs[1]["events"]], ["start", "note", "end"])
        self.assertEqual(runs[1]["end"]["verified"], ["tests pass"])

    def test_bad_json_reports_file_and_line(self):
        self.log.write_text('{"event":"start","run":"ok"}\n{bad json\n')

        with self.assertRaisesRegex(ValueError, rf"{self.log}:2: invalid JSON"):
            load_runs(self.log)

    def test_page_escapes_run_text_and_says_telemetry_is_not_collected(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "xss", "task": "<script>alert(1)</script>", "agent": "hermes"},
            {"ts": "2026-10-01T10:01:00+00:00", "event": "end", "run": "xss", "status": "done", "verified": [], "unverified": []},
        )

        page = render_page(load_runs(self.log), selected_id="xss")

        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("Token and tool telemetry is not collected yet", page)
        self.assertIn("<title>ClearStack runs</title>", page)


if __name__ == "__main__":
    unittest.main()
