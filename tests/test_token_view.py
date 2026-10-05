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


def _write_state_db(db_path, sessions, usage, messages=(), prompts=(), billing=()):
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
    conn.execute("ALTER TABLE session_model_usage ADD COLUMN billing_provider TEXT")
    conn.execute("ALTER TABLE session_model_usage ADD COLUMN billing_mode TEXT")
    conn.execute("ALTER TABLE session_model_usage ADD COLUMN cost_status TEXT")
    conn.execute("ALTER TABLE session_model_usage ADD COLUMN cost_source TEXT")
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
    conn.executemany("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", sessions)
    conn.executemany(
        "INSERT INTO session_model_usage "
        "(session_id, model, api_call_count, input_tokens, output_tokens, cache_read_tokens, "
        "cache_write_tokens, actual_cost_usd, estimated_cost_usd, last_seen) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        usage,
    )
    conn.executemany(
        "UPDATE session_model_usage SET billing_provider=?, billing_mode=?, cost_status=?, cost_source=? "
        "WHERE session_id=? AND model=?",
        billing,
    )
    conn.executemany("INSERT INTO messages VALUES (?,?,?,?,?)", messages)
    conn.executemany("INSERT INTO system_prompts VALUES (?,?)", prompts)
    conn.commit()
    conn.close()
    return db_path


class TokenViewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temp.name)
        self.empty_profiles = self.state_dir / "no-profiles-here"

    def tearDown(self):
        self.temp.cleanup()

    def _render(self, db):
        with patch("clearstack.token_view._state_db_path", return_value=db), \
             patch("clearstack.token_view._profile_dbs_dir", return_value=self.empty_profiles):
            return render_tokens_page()

    def _make_state_db(self):
        now = 1_800_000_000
        return _write_state_db(
            self.state_dir / "state.db",
            sessions=[
                ("s1", "desktop", "Fix bug", None, "gpt-5", now - 1000, 50, 10, 1_000_000, 100_000, 10_000_000, 1_000_000, 0.5, None),
                ("s2", "cli", "Quick task", None, "gpt-4", now - 2000, 5, 2, 10_000, 1_000, 100_000, 10_000, None, None),
            ],
            usage=[
                ("s1", "gpt-5", 10, 1_000_000, 100_000, 10_000_000, 1_000_000, 0.5, None, now - 1000),
                ("s2", "gpt-4", 2, 10_000, 1_000, 100_000, 10_000, None, None, now - 2000),
            ],
            messages=[
                (1, "s1", "tool", "read_file", now - 500),
                (2, "s1", "tool", "terminal", now - 400),
            ],
            prompts=[("abc123", "x" * 50_000), ("def456", "y" * 20_000)],
        )

    def test_page_renders_headline_cards(self):
        page = self._render(self._make_state_db())
        self.assertIn("fresh input tokens", page)
        self.assertIn("1.0M", page)
        self.assertIn("output tokens", page)
        self.assertIn("cache-read tokens", page)
        self.assertIn("API calls", page)

    def test_page_shows_by_model_bars(self):
        page = self._render(self._make_state_db())
        self.assertIn("gpt-5", page)
        self.assertIn("gpt-4", page)

    def test_page_shows_daily_stacked_and_legend(self):
        page = self._render(self._make_state_db())
        self.assertIn("Fresh input per day", page)
        self.assertIn("gpt-5", page)

    def test_page_shows_session_size_buckets(self):
        page = self._render(self._make_state_db())
        self.assertIn("Session-size buckets", page)
        self.assertIn("50-99", page)
        self.assertIn("&lt;20 msgs", page)

    def test_page_shows_surface_breakdown(self):
        page = self._render(self._make_state_db())
        self.assertIn("By surface", page)
        self.assertIn("desktop", page)
        self.assertIn("cli", page)

    def test_page_shows_top_sessions_table(self):
        page = self._render(self._make_state_db())
        self.assertIn("Top sessions by fresh input", page)
        self.assertIn("Fix bug", page)
        self.assertIn("Quick task", page)
        self.assertIn("<th>fresh in</th>", page)

    def test_page_shows_tool_volume(self):
        page = self._render(self._make_state_db())
        self.assertIn("Tool result volume", page)
        self.assertIn("read_file", page)
        self.assertIn("terminal", page)

    def test_page_shows_prompt_overhead(self):
        page = self._render(self._make_state_db())
        self.assertIn("Fixed per-turn overhead anatomy", page)
        self.assertIn("50.0K chars", page)
        self.assertIn("20.0K chars", page)

    def test_page_shows_billing_groups_and_marks_missing_provider_quotas_unknown(self):
        db = _write_state_db(
            self.state_dir / "billing.db",
            sessions=[
                ("metered", "desktop", "Metered task", None, "gpt-5", 1_800_000_000, 1, 1, 100, 10, 0, 0, None, 0.42),
                ("included", "desktop", "Included task", None, "claude", 1_800_000_000, 1, 1, 200, 20, 0, 0, None, 1.50),
            ],
            usage=[
                ("metered", "gpt-5", 1, 100, 10, 0, 0, 0.42, None, 1_800_000_000),
                ("included", "claude", 1, 200, 20, 0, 0, 1.50, None, 1_800_000_000),
            ],
            billing=[
                ("openai", "api", "actual", "provider", "metered", "gpt-5"),
                ("anthropic", "subscription_included", "included", "none", "included", "claude"),
            ],
        )

        page = self._render(db)

        self.assertIn("Billing and quota signals", page)
        self.assertIn("openai", page)
        self.assertIn("$0.42 actual", page)
        self.assertIn("Included with subscription", page)
        self.assertIn("not stored by Hermes", page)
        self.assertIn("Set a 14-day spend guardrail", page)

    def test_token_page_has_a_persistent_theme_picker_and_custom_palette_inputs(self):
        page = self._render(self._make_state_db())

        self.assertIn("Appearance", page)
        self.assertIn("ClearStack theme", page)
        self.assertIn("data-theme-token=\"aqua\"", page)
        self.assertIn("clearstack.theme", page)

    def test_missing_state_db_renders_empty_state(self):
        with patch("clearstack.token_view._state_db_path", return_value=Path("/no/such/state.db")), \
             patch("clearstack.token_view._profile_dbs_dir", return_value=self.empty_profiles):
            page = render_tokens_page()
        self.assertIn("No state.db found", page)

    def test_profile_dbs_are_merged_and_labeled(self):
        default_db = self._make_state_db()
        now = 1_800_000_000
        profiles_dir = self.state_dir / "profiles"
        scribe_dir = profiles_dir / "scribe"
        scribe_dir.mkdir(parents=True)
        _write_state_db(
            scribe_dir / "state.db",
            sessions=[
                ("k1", "kanban", "Work card t_x", None, "kimi-k3", now - 900,
                 80, 30, 2_000_000, 50_000, 20_000_000, 500_000, None, None),
            ],
            usage=[
                ("k1", "kimi-k3", 30, 2_000_000, 50_000, 20_000_000, 500_000, None, None, now - 900),
            ],
            messages=[(1, "k1", "tool", "kanban_show", now - 800)],
            prompts=[("abc123", "x" * 50_000)],
        )
        with patch("clearstack.token_view._state_db_path", return_value=default_db), \
             patch("clearstack.token_view._profile_dbs_dir", return_value=profiles_dir):
            page = render_tokens_page()
        # merged headline: 1.0M default + 2.0M profile fresh input
        self.assertIn("3.0M", page)
        # surface row for the profile db is labeled with the profile name
        self.assertIn("kanban · scribe", page)
        # top sessions table names the db a session came from
        self.assertIn("Work card t_x", page)
        # shared prompt hash is deduped, not double counted
        self.assertIn("2 distinct prompt hash", page)
        # sources note lists what was read
        self.assertIn("scribe", page)

    def test_dashboard_tokens_route_returns_200(self):
        db = self._make_state_db()
        with patch("clearstack.token_view._state_db_path", return_value=db), \
             patch("clearstack.token_view._profile_dbs_dir", return_value=self.empty_profiles):
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
