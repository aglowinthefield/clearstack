import json
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from clearstack.dashboard import DashboardHandler
from clearstack.token_view import render_tokens_page


class TokenViewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _make_state_db(self):
        db_path = self.state_dir / "state.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE sessions ("
            " id TEXT PRIMARY KEY,"
            " source TEXT,"
            " title TEXT,"
            " display_name TEXT,"
            " model TEXT,"
            " started_at REAL,"
            " message_count INTEGER DEFAULT 0,"
            " api_call_count INTEGER DEFAULT 0,"
            " input_tokens INTEGER DEFAULT 0,"
            " output_tokens INTEGER DEFAULT 0,"
            " cache_read_tokens INTEGER DEFAULT 0,"
            " cache_write_tokens INTEGER DEFAULT 0,"
            " actual_cost_usd REAL,"
            " estimated_cost_usd REAL"
            ")"
        )
        conn.execute(
            "CREATE TABLE session_model_usage ("
            " session_id TEXT,"
            " model TEXT,"
            " api_call_count INTEGER DEFAULT 0,"
            " input_tokens INTEGER DEFAULT 0,"
            " output_tokens INTEGER DEFAULT 0,"
            " cache_read_tokens INTEGER DEFAULT 0,"
            " cache_write_tokens INTEGER DEFAULT 0,"
            " actual_cost_usd REAL,"
            " estimated_cost_usd REAL,"
            " last_seen REAL"
            ")"
        )
        conn.execute(
            "CREATE TABLE messages ("
            " id INTEGER PRIMARY KEY,"
            " session_id TEXT,"
            " role TEXT,"
            " tool_name TEXT,"
            " timestamp REAL"
            ")"
        )
        conn.execute(
            "CREATE TABLE system_prompts ("
            " hash TEXT PRIMARY KEY,"
            " prompt TEXT"
            ")"
        )
        now = 1_800_000_000
        conn.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("s1", "desktop", "Fix bug", None, "gpt-5", now - 1000, 50, 10, 1_000_000, 100_000, 10_000_000, 1_000_000, 0.5, None),
        )
        conn.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("s2", "cli", "Quick task", None, "gpt-4", now - 2000, 5, 2, 10_000, 1_000, 100_000, 10_000, None, None),
        )
        conn.execute(
            "INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("s1", "gpt-5", 10, 1_000_000, 100_000, 10_000_000, 1_000_000, 0.5, None, now - 1000),
        )
        conn.execute(
            "INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("s2", "gpt-4", 2, 10_000, 1_000, 100_000, 10_000, None, None, now - 2000),
        )
        conn.execute(
            "INSERT INTO messages VALUES (?,?,?,?,?)",
            (1, "s1", "tool", "read_file", now - 500),
        )
        conn.execute(
            "INSERT INTO messages VALUES (?,?,?,?,?)",
            (2, "s1", "tool", "terminal", now - 400),
        )
        conn.execute(
            "INSERT INTO system_prompts VALUES (?,?)",
            ("abc123", "x" * 50_000),
        )
        conn.execute(
            "INSERT INTO system_prompts VALUES (?,?)",
            ("def456", "y" * 20_000),
        )
        conn.commit()
        conn.close()
        return db_path

    def test_page_renders_headline_cards(self):
        db = self._make_state_db()
        with patch("clearstack.token_view._state_db_path", return_value=db):
            page = render_tokens_page()
        self.assertIn("fresh input tokens", page)
        self.assertIn("1.0M", page)
        self.assertIn("output tokens", page)
        self.assertIn("cache-read tokens", page)
        self.assertIn("API calls", page)

    def test_page_shows_by_model_bars(self):
        db = self._make_state_db()
        with patch("clearstack.token_view._state_db_path", return_value=db):
            page = render_tokens_page()
        self.assertIn("gpt-5", page)
        self.assertIn("gpt-4", page)

    def test_page_shows_daily_stacked_and_legend(self):
        db = self._make_state_db()
        with patch("clearstack.token_view._state_db_path", return_value=db):
            page = render_tokens_page()
        self.assertIn("Fresh input per day", page)
        self.assertIn("gpt-5", page)

    def test_page_shows_session_size_buckets(self):
        db = self._make_state_db()
        with patch("clearstack.token_view._state_db_path", return_value=db):
            page = render_tokens_page()
        self.assertIn("Session-size buckets", page)
        self.assertIn("50-99", page)
        self.assertIn("&lt;20 msgs", page)

    def test_page_shows_surface_breakdown(self):
        db = self._make_state_db()
        with patch("clearstack.token_view._state_db_path", return_value=db):
            page = render_tokens_page()
        self.assertIn("By surface", page)
        self.assertIn("desktop", page)
        self.assertIn("cli", page)

    def test_page_shows_top_sessions_table(self):
        db = self._make_state_db()
        with patch("clearstack.token_view._state_db_path", return_value=db):
            page = render_tokens_page()
        self.assertIn("Top sessions by fresh input", page)
        self.assertIn("Fix bug", page)
        self.assertIn("Quick task", page)
        self.assertIn("<th>fresh in</th>", page)

    def test_page_shows_tool_volume(self):
        db = self._make_state_db()
        with patch("clearstack.token_view._state_db_path", return_value=db):
            page = render_tokens_page()
        self.assertIn("Tool result volume", page)
        self.assertIn("read_file", page)
        self.assertIn("terminal", page)

    def test_page_shows_prompt_overhead(self):
        db = self._make_state_db()
        with patch("clearstack.token_view._state_db_path", return_value=db):
            page = render_tokens_page()
        self.assertIn("Fixed per-turn overhead anatomy", page)
        self.assertIn("50.0K chars", page)
        self.assertIn("20.0K chars", page)

    def test_missing_state_db_renders_empty_state(self):
        with patch("clearstack.token_view._state_db_path", return_value=Path("/no/such/state.db")):
            page = render_tokens_page()
        self.assertIn("No state.db found", page)

    def test_dashboard_tokens_route_returns_200(self):
        db = self._make_state_db()
        with patch("clearstack.token_view._state_db_path", return_value=db):
            server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            self.addCleanup(thread.join, timeout=2)
            try:
                req = urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/tokens", timeout=5)
                self.assertEqual(req.status, 200)
                body = req.read().decode("utf-8")
                self.assertIn("Token spend", body)
                self.assertIn("gpt-5", body)
            finally:
                server.server_close()


if __name__ == "__main__":
    unittest.main()
