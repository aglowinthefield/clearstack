import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clearstack.dashboard import create_server, default_log_path, load_runs, parse_args, render_page


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.log = Path(self.temp.name) / "runs.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def write_events(self, *events):
        self.log.write_text("".join(json.dumps(event) + "\n" for event in events))

    def write_hermes_db(self):
        db_path = Path(self.temp.name) / "state.db"
        with closing(sqlite3.connect(db_path)) as db:
            db.execute("""CREATE TABLE sessions (
                id TEXT PRIMARY KEY, tool_call_count INTEGER, input_tokens INTEGER,
                output_tokens INTEGER, api_call_count INTEGER, estimated_cost_usd REAL,
                actual_cost_usd REAL, cost_status TEXT
            )""")
            db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       ("session-1", 4, 1200, 300, 6, 0.12, None, "estimated"))
            db.commit()
        return db_path

    def test_empty_xdg_state_home_uses_default_state_directory(self):
        home = Path(self.temp.name) / "home"
        with patch.dict("os.environ", {"XDG_STATE_HOME": ""}), patch("clearstack.dashboard.Path.home", return_value=home):
            self.assertEqual(default_log_path(), home / ".local" / "state" / "clearstack" / "runs.jsonl")

    def test_dashboard_defaults_to_loopback_and_accepts_a_specific_host(self):
        self.assertEqual(parse_args([]).host, "127.0.0.1")
        self.assertEqual(parse_args(["--host", "mochi", "--port", "8765"]).host, "mochi")

    def test_server_binds_the_requested_resolved_host(self):
        server = create_server(host="localhost", port=0)
        try:
            self.assertEqual(server.server_address[0], "127.0.0.1")
            self.assertGreater(server.server_address[1], 0)
        finally:
            server.server_close()

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

    def test_load_runs_attaches_hermes_usage_only_to_matching_session(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "tracked", "agent": "hermes-agent", "session": "session-1"},
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "unmatched", "agent": "hermes-agent"},
        )

        runs = load_runs(self.log, telemetry_path=self.write_hermes_db())

        self.assertEqual(runs[1]["telemetry"], {
            "available": True, "tool_call_count": 4, "input_tokens": 1200, "output_tokens": 300,
            "api_call_count": 6, "estimated_cost_usd": 0.12, "actual_cost_usd": None,
            "cost_status": "estimated",
        })
        self.assertEqual(runs[0]["telemetry"], {"available": False, "reason": "no linked Hermes session"})

    def test_dashboard_visualizes_measured_usage_without_an_efficiency_grade(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "tracked", "agent": "hermes-agent", "session": "session-1", "task": "measured task"},
            {"ts": "2026-10-01T10:01:00+00:00", "event": "start", "run": "same-session", "agent": "hermes-agent", "session": "session-1", "task": "second task"},
        )

        page = render_page(load_runs(self.log, telemetry_path=self.write_hermes_db()), selected_id="tracked")

        self.assertIn("1,500", page)
        self.assertIn("4", page)
        self.assertIn("6", page)
        self.assertIn("0.12", page)
        self.assertIn("Hermes session usage", page)
        self.assertIn("Totals may span multiple ClearStack runs", page)
        self.assertNotIn("efficiency score", page.lower())
        self.assertNotIn("session-1", page)
        self.assertEqual(page.count("class=usage-row"), 2)


if __name__ == "__main__":
    unittest.main()
