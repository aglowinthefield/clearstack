import importlib.util
import json
import sqlite3
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

MINE = Path(__file__).resolve().parent.parent / "skills" / "clear-reflect" / "scripts" / "mine"

_loader = SourceFileLoader("mine_module", str(MINE))
_spec = importlib.util.spec_from_loader("mine_module", _loader)
mine_module = importlib.util.module_from_spec(_spec)
_loader.exec_module(mine_module)


def _make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_call_id TEXT,
            tool_calls TEXT,
            tool_name TEXT,
            _compressed_summary INTEGER NOT NULL DEFAULT 0,
            timestamp REAL DEFAULT 0
        )
    """)
    return conn


def _insert_assistant(conn, session_id, msg_id, tool_calls, compressed=0):
    conn.execute(
        """
        INSERT INTO messages (id, session_id, role, tool_calls, _compressed_summary)
        VALUES (?, ?, 'assistant', ?, ?)
        """,
        (msg_id, session_id, json.dumps(tool_calls), compressed),
    )


def _insert_tool(conn, session_id, msg_id, tool_call_id, content, tool_name=None):
    conn.execute(
        """
        INSERT INTO messages (id, session_id, role, tool_call_id, content, tool_name)
        VALUES (?, ?, 'tool', ?, ?, ?)
        """,
        (msg_id, session_id, tool_call_id, content, tool_name),
    )


class ParseToolCallsTest(unittest.TestCase):
    def test_parses_standard_function_call(self):
        raw = json.dumps([{
            "id": "call_1",
            "type": "function",
            "function": {"name": "terminal", "arguments": '{"command":"ls"}'},
        }])
        parsed = mine_module.parse_tool_calls(raw)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0], ("call_1", "terminal", {"command": "ls"}))

    def test_returns_empty_on_bad_json(self):
        self.assertEqual(mine_module.parse_tool_calls("not json"), [])


class NormalizeCallTest(unittest.TestCase):
    def test_terminal_strips_workdir(self):
        norm = mine_module.normalize_call("terminal", {
            "command": "cd /home/user/proj && ls",
            "workdir": "/home/user/proj",
        })
        self.assertEqual(norm, "terminal: ls")

    def test_read_file_ignores_offset(self):
        norm = mine_module.normalize_call("read_file", {
            "path": "/a/b.py",
            "offset": 10,
            "limit": 20,
        })
        self.assertEqual(norm, "read_file: /a/b.py")

    def test_search_files_uses_pattern(self):
        norm = mine_module.normalize_call("search_files", {
            "pattern": "foo",
            "path": "/a/b",
        })
        self.assertEqual(norm, "search_files: foo")


class OversizedResultsTest(unittest.TestCase):
    def test_groups_by_tool_name_and_shape(self):
        conn = _make_db()
        tc = [{"id": "c1", "type": "function",
               "function": {"name": "terminal", "arguments": '{"command":"ls /a"}'}}]
        _insert_assistant(conn, "s1", 1, tc)
        _insert_tool(conn, "s1", 2, "c1", "x" * 25000, "terminal")

        tc2 = [{"id": "c2", "type": "function",
                "function": {"name": "terminal", "arguments": '{"command":"ls /b"}'}}]
        _insert_assistant(conn, "s1", 3, tc2)
        _insert_tool(conn, "s1", 4, "c2", "y" * 30000, "terminal")

        _insert_tool(conn, "s1", 5, "c3", "z" * 1000, "read_file")

        findings = mine_module.mine_oversized(conn, threshold=20000)
        conn.close()

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["tool_name"], "terminal")
        self.assertEqual(findings[0]["count"], 2)
        self.assertEqual(findings[0]["max_size"], 30000)
        self.assertEqual(findings[0]["total_size"], 55000)

    def test_empty_db_returns_empty(self):
        conn = _make_db()
        findings = mine_module.mine_oversized(conn)
        conn.close()
        self.assertEqual(findings, [])


class RepeatedCommandsTest(unittest.TestCase):
    def test_finds_three_repeats_in_one_session(self):
        conn = _make_db()
        for i in range(3):
            tc = [{"id": f"c{i}", "type": "function",
                   "function": {"name": "terminal",
                                "arguments": '{"command":"npm test"}'}}]
            _insert_assistant(conn, "s1", i + 1, tc)

        findings = mine_module.mine_repeats(conn, min_count=3)
        conn.close()

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["count"], 3)
        self.assertEqual(findings[0]["tool_name"], "terminal")
        self.assertFalse(findings[0]["compaction_adjacent"])

    def test_normalization_collapses_trivial_differences(self):
        conn = _make_db()
        for i in range(3):
            args = json.dumps({"path": "/a.py", "offset": i + 1})
            tc = [{"id": f"c{i}", "type": "function",
                   "function": {"name": "read_file", "arguments": args}}]
            _insert_assistant(conn, "s1", i + 1, tc)

        findings = mine_module.mine_repeats(conn, min_count=3)
        conn.close()

        # Same path with different offsets collapses to one normalized command.
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["normalized_command"], "read_file: /a.py")

    def test_compaction_adjacent_flagged_when_spanning(self):
        conn = _make_db()
        tc = [{"id": "c1", "type": "function",
               "function": {"name": "terminal", "arguments": '{"command":"npm test"}'}}]
        _insert_assistant(conn, "s1", 1, tc)
        _insert_assistant(conn, "s1", 2, tc, compressed=1)
        _insert_assistant(conn, "s1", 3, tc)
        _insert_assistant(conn, "s1", 4, tc)

        findings = mine_module.mine_repeats(conn, min_count=3)
        conn.close()

        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0]["compaction_adjacent"])

    def test_not_flagged_when_all_before_compaction(self):
        conn = _make_db()
        tc = [{"id": "c1", "type": "function",
               "function": {"name": "terminal", "arguments": '{"command":"npm test"}'}}]
        _insert_assistant(conn, "s1", 1, tc)
        _insert_assistant(conn, "s1", 2, tc)
        _insert_assistant(conn, "s1", 3, tc)
        _insert_assistant(conn, "s1", 4, tc, compressed=1)

        findings = mine_module.mine_repeats(conn, min_count=3)
        conn.close()

        self.assertEqual(len(findings), 1)
        self.assertFalse(findings[0]["compaction_adjacent"])


class MineIntegrationTest(unittest.TestCase):
    def test_missing_db_reports_note_not_traceback(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "nonexistent.db"
            runs_path = Path(td) / "runs.jsonl"
            report = mine_module.mine(db_path, runs_path)

        self.assertIn("state_db", report["sources"])
        self.assertIn("not found", report["sources"]["state_db"]["note"])
        self.assertEqual(report["findings"]["oversized_results"], [])
        self.assertEqual(report["findings"]["repeated_commands"], [])

    def test_summary_counts_match_findings(self):
        tc = [{"id": "c1", "type": "function",
               "function": {"name": "terminal", "arguments": '{"command":"npm test"}'}}]

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "state.db"
            runs_path = Path(td) / "runs.jsonl"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    tool_call_id TEXT,
                    tool_calls TEXT,
                    tool_name TEXT,
                    _compressed_summary INTEGER NOT NULL DEFAULT 0,
                    timestamp REAL DEFAULT 0
                )
                """
            )
            _insert_assistant(conn, "s1", 1, tc)
            _insert_tool(conn, "s1", 2, "c1", "x" * 25000, "terminal")
            _insert_assistant(conn, "s1", 3, tc)
            _insert_assistant(conn, "s1", 4, tc)
            conn.commit()
            conn.close()

            report = mine_module.mine(db_path, runs_path)

        self.assertEqual(len(report["findings"]["oversized_results"]), 1)
        self.assertEqual(len(report["findings"]["repeated_commands"]), 1)
        self.assertIn("1 finding(s)", report["summary"])


if __name__ == "__main__":
    unittest.main()
