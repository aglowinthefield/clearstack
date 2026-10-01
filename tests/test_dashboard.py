import json
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from clearstack.dashboard import DashboardHandler, default_log_path, load_runs, render_page


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

    def test_current_focus_is_the_latest_focus_event(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "r1", "task": "migrate billing", "agent": "hermes"},
            {"ts": "2026-10-01T10:01:00+00:00", "event": "focus", "run": "r1", "text": "picking rollout strategy"},
            {"ts": "2026-10-01T10:02:00+00:00", "event": "focus", "run": "r1", "text": "wiring the flag now"},
        )

        runs = load_runs(self.log)

        self.assertEqual(runs[0]["current_focus"], "wiring the flag now")

    def test_run_with_no_focus_event_has_none_current_focus(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "r1", "task": "quick fix", "agent": "hermes"},
        )

        self.assertIsNone(load_runs(self.log)[0]["current_focus"])

    def test_detail_view_renders_the_focus_callout(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "r1", "task": "migrate billing", "agent": "hermes"},
            {"ts": "2026-10-01T10:01:00+00:00", "event": "focus", "run": "r1", "text": "<b>waiting</b> on rollout call"},
        )

        page = render_page(load_runs(self.log), selected_id="r1")

        self.assertIn("Current focus", page)
        self.assertIn("&lt;b&gt;waiting&lt;/b&gt; on rollout call", page)

    def test_table_row_shows_focus_hint_only_for_open_runs(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "open-run", "task": "ongoing work", "agent": "hermes"},
            {"ts": "2026-10-01T10:01:00+00:00", "event": "focus", "run": "open-run", "text": "blocked on review"},
            {"ts": "2026-10-01T09:00:00+00:00", "event": "start", "run": "closed-run", "task": "finished work", "agent": "hermes"},
            {"ts": "2026-10-01T09:01:00+00:00", "event": "focus", "run": "closed-run", "text": "stale focus text"},
            {"ts": "2026-10-01T09:02:00+00:00", "event": "end", "run": "closed-run", "status": "done"},
        )

        page = render_page(load_runs(self.log))
        table_section = page.split("<section class=\"panel glass activity-panel\"")[0]

        self.assertIn("blocked on review", table_section)
        self.assertNotIn("stale focus text", table_section)

    def test_page_shows_no_telemetry_banner_and_renders_title(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "r1", "task": "plain run", "agent": "hermes"},
            {"ts": "2026-10-01T10:01:00+00:00", "event": "end", "run": "r1", "status": "done", "verified": [], "unverified": []},
        )

        page = render_page(load_runs(self.log))

        self.assertIn("Token and tool telemetry is not collected yet", page)
        self.assertIn("<title>ClearStack runs</title>", page)

    def test_run_with_telemetry_shows_cost_in_table_summary_and_detail(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "r1", "task": "priced run", "agent": "hermes"},
            {"ts": "2026-10-01T10:01:00+00:00", "event": "end", "run": "r1", "status": "done",
             "verified": [], "unverified": [],
             "telemetry": {"source": "hermes", "tokens": {"input": 100, "output": 20, "cache_read": 0, "cache_write": 0},
                           "cost_usd": 1.2345, "tool_calls": 7}},
        )

        page = render_page(load_runs(self.log))

        self.assertNotIn("Token and tool telemetry is not collected yet", page)
        self.assertIn("$1.23", page)
        self.assertIn("total cost", page)
        self.assertIn("<th>Cost</th>", page)

        detail = render_page(load_runs(self.log), selected_id="r1")
        self.assertIn("Telemetry · hermes", detail)
        self.assertIn("$1.2345", detail)
        self.assertIn("7", detail)

    def test_detail_shows_a_tool_mix_donut_when_telemetry_has_a_breakdown(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "r1", "task": "run", "agent": "hermes"},
            {"ts": "2026-10-01T10:01:00+00:00", "event": "end", "run": "r1", "status": "done",
             "verified": [], "unverified": [],
             "telemetry": {"source": "hermes", "tokens": {}, "cost_usd": 0.5, "tool_calls": 5,
                           "tool_breakdown": {"search_files": 3, "terminal": 2}}},
        )

        detail = render_page(load_runs(self.log), selected_id="r1")

        self.assertIn("<div class=donut-chart", detail)
        self.assertIn("conic-gradient", detail)
        self.assertIn("search_files", detail)
        self.assertIn("terminal", detail)

    def test_detail_has_no_donut_when_telemetry_lacks_a_breakdown(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "r1", "task": "run", "agent": "hermes"},
            {"ts": "2026-10-01T10:01:00+00:00", "event": "end", "run": "r1", "status": "done",
             "verified": [], "unverified": [],
             "telemetry": {"source": "hermes", "tokens": {}, "cost_usd": 0.5, "tool_calls": 0}},
        )

        detail = render_page(load_runs(self.log), selected_id="r1")
        self.assertNotIn("<div class=donut-chart", detail)

    def test_main_page_shows_aggregate_tool_mix_donut_across_runs(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "a", "task": "a", "agent": "hermes"},
            {"ts": "2026-10-01T10:01:00+00:00", "event": "end", "run": "a", "status": "done",
             "verified": [], "unverified": [],
             "telemetry": {"source": "hermes", "tokens": {}, "cost_usd": 0.1, "tool_calls": 2,
                           "tool_breakdown": {"shell": 2}}},
            {"ts": "2026-10-01T10:02:00+00:00", "event": "start", "run": "b", "task": "b", "agent": "hermes"},
            {"ts": "2026-10-01T10:03:00+00:00", "event": "end", "run": "b", "status": "done",
             "verified": [], "unverified": [],
             "telemetry": {"source": "hermes", "tokens": {}, "cost_usd": 0.1, "tool_calls": 1,
                           "tool_breakdown": {"shell": 1}}},
        )

        page = render_page(load_runs(self.log))

        self.assertIn("Tool mix", page)
        self.assertIn("<div class=donut-chart", page)
        self.assertIn(">shell<", page)
        self.assertIn("3 · 100%", page)

    def test_main_page_omits_tool_mix_donut_without_telemetry(self):
        page = render_page(load_runs(self.log))
        self.assertNotIn("Tool mix", page)


    def test_page_includes_an_eventsource_script_for_realtime_updates(self):
        page = render_page(load_runs(self.log))
        self.assertIn("new EventSource(\"/events\")", page)
        self.assertIn("</script>", page)

    def test_open_run_duration_cell_carries_data_for_client_side_ticking(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "open1", "task": "still going", "agent": "hermes"},
        )

        page = render_page(load_runs(self.log))

        self.assertIn("data-duration", page)
        self.assertIn('data-started="2026-10-01T10:00:00+00:00"', page)
        self.assertIn('data-status="open"', page)

    def test_activity_feed_shows_events_newest_first_across_runs(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "a", "task": "task a", "agent": "hermes"},
            {"ts": "2026-10-01T10:05:00+00:00", "event": "start", "run": "b", "task": "task b", "agent": "codex"},
            {"ts": "2026-10-01T10:06:00+00:00", "event": "note", "run": "a", "text": "found the bug"},
            {"ts": "2026-10-01T10:10:00+00:00", "event": "end", "run": "b", "status": "done", "verified": [], "unverified": []},
        )

        page = render_page(load_runs(self.log))

        idx_end = page.index("task b — done")
        idx_note = page.index("found the bug")
        idx_start_a = page.index("task a", idx_note)
        self.assertLess(idx_end, idx_note)
        self.assertLess(idx_note, idx_start_a)
        self.assertIn("activity-list", page)

    def test_activity_feed_has_empty_state_with_no_runs(self):
        page = render_page(load_runs(self.log))
        self.assertIn("No activity yet", page)

    def test_table_nests_subagent_run_under_its_parent(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "parent1", "task": "parent task", "agent": "hermes"},
            {"ts": "2026-10-01T10:01:00+00:00", "event": "start", "run": "child1", "task": "child task",
             "agent": "hermes", "parent_run_id": "parent1", "spawned_by": "delegate_task"},
        )

        page = render_page(load_runs(self.log))

        idx_parent = page.index("parent task")
        idx_child = page.index("child task")
        self.assertLess(idx_parent, idx_child)
        self.assertIn("lineage-mark", page)

    def test_detail_shows_parent_link_and_self_report_banner_for_a_child_run(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "parent1", "task": "parent task", "agent": "hermes"},
            {"ts": "2026-10-01T10:01:00+00:00", "event": "start", "run": "child1", "task": "child task",
             "agent": "hermes", "parent_run_id": "parent1", "spawned_by": "delegate_task"},
        )

        detail = render_page(load_runs(self.log), selected_id="child1")

        self.assertIn("Spawned by", detail)
        self.assertIn("parent task", detail)
        self.assertIn("Self-reported by delegate_task", detail)
        self.assertIn("not verified evidence", detail)

    def test_detail_lists_child_runs_for_a_parent(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "parent1", "task": "parent task", "agent": "hermes"},
            {"ts": "2026-10-01T10:01:00+00:00", "event": "start", "run": "child1", "task": "child task",
             "agent": "hermes", "parent_run_id": "parent1", "spawned_by": "delegate_task"},
        )

        detail = render_page(load_runs(self.log), selected_id="parent1")

        self.assertIn("Subagents (1)", detail)
        self.assertIn("child task", detail)
        self.assertNotIn("Self-reported by", detail)

    def test_run_with_unknown_parent_id_is_not_dropped(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "orphan1", "task": "orphan task",
             "agent": "hermes", "parent_run_id": "does-not-exist", "spawned_by": "subagent"},
        )

        page = render_page(load_runs(self.log))
        self.assertIn("orphan task", page)

    def test_status_mix_bar_reflects_counts(self):
        self.write_events(
            {"ts": "2026-10-01T10:00:00+00:00", "event": "start", "run": "a", "task": "a", "agent": "hermes"},
            {"ts": "2026-10-01T10:01:00+00:00", "event": "start", "run": "b", "task": "b", "agent": "hermes"},
            {"ts": "2026-10-01T10:02:00+00:00", "event": "end", "run": "b", "status": "done", "verified": [], "unverified": []},
        )

        page = render_page(load_runs(self.log))

        self.assertIn("<div class=status-mix>", page)
        self.assertIn('class="mix-seg mix-aqua"', page)
        self.assertIn('class="mix-seg mix-mint"', page)

    def test_status_mix_empty_with_no_runs(self):
        page = render_page(load_runs(self.log))
        self.assertNotIn("<div class=status-mix>", page)


class SSETest(unittest.TestCase):
    def test_events_endpoint_pushes_update_when_the_log_file_changes(self):
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        log_path = Path(state.name) / "clearstack" / "runs.jsonl"
        log_path.parent.mkdir(parents=True)
        log_path.write_text("")

        with patch.dict("os.environ", {"XDG_STATE_HOME": state.name}):
            server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            self.addCleanup(thread.join, timeout=2)
            try:
                conn = urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/events", timeout=5)
                self.addCleanup(conn.close)
                time.sleep(0.1)
                log_path.write_text('{"event":"start","run":"r1"}\n')
                deadline = time.monotonic() + 5
                chunk = b""
                while time.monotonic() < deadline and b"event: update" not in chunk:
                    chunk += conn.read1(256)
                self.assertIn(b"event: update", chunk)
            finally:
                server.server_close()

if __name__ == "__main__":
    unittest.main()
