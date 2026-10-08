import importlib.util
import json
import sqlite3
import tempfile
import unittest
import unittest.mock
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

    def test_read_file_keys_on_range(self):
        def norm(offset, limit):
            return mine_module.normalize_call("read_file", {
                "path": "/a/b.py", "offset": offset, "limit": limit,
            })
        self.assertEqual(norm(10, 20), "read_file: /a/b.py [10:20]")
        self.assertEqual(norm(10, 20), norm(10, 20))
        self.assertNotEqual(norm(10, 20), norm(30, 20))

    def test_generic_tool_keys_on_argument_values(self):
        github = mine_module.normalize_call("skill_view", {"name": "github"})
        review = mine_module.normalize_call("skill_view", {"name": "code-review"})
        self.assertNotEqual(github, review)
        self.assertEqual(github, mine_module.normalize_call("skill_view", {"name": "github"}))

    def test_generic_tool_long_arguments_stay_distinct(self):
        def norm(new):
            return mine_module.normalize_call("patch", {
                "path": "/a/b.py", "old_string": "x" * 500, "new_string": new,
            })
        self.assertNotEqual(norm("one"), norm("two"))
        self.assertLess(len(norm("one")), 200)

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

    def test_paging_through_a_file_is_not_a_repeat(self):
        conn = _make_db()
        for i in range(3):
            args = json.dumps({"path": "/a.py", "offset": i + 1})
            tc = [{"id": f"c{i}", "type": "function",
                   "function": {"name": "read_file", "arguments": args}}]
            _insert_assistant(conn, "s1", i + 1, tc)

        findings = mine_module.mine_repeats(conn, min_count=3)
        conn.close()

        # Each offset reads different content, so three pages are not three repeats.
        self.assertEqual(findings, [])

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


class DiscordSummaryTest(unittest.TestCase):
    def test_compacts_findings_into_discord_markdown(self):
        oversized = [
            {
                "tool_name": "skill_view",
                "command_shape": "skill_view: <args>",
                "count": count,
                "max_size": 41_722,
                "total_size": 1_263_822,
            }
            for count in range(1, 7)
        ]
        repeats = [
            {
                "normalized_command": "patch(('mode', 'patch'))",
                "count": count,
                "session_id": "20260921_141506_bd0bfe",
                "compaction_adjacent": False,
            }
            for count in range(3, 9)
        ]
        unused = {
            "note": None,
            "never_used_count": 44,
            "total_skills": 80,
            "never_used_cost": 4_772,
            "total_catalog_cost": 7_736,
            "skills": [
                {"name": "agents-sdk", "catalog_cost": 441},
                {"name": "cloudflare", "catalog_cost": 378},
            ],
        }

        summary = mine_module.emit_discord_summary(
            oversized,
            repeats,
            unused,
            {"note": "domain map unavailable"},
            {"note": "no lane candidates"},
            {"note": "run data unavailable"},
        )

        self.assertIn("**Oversized results** (6 patterns over 20,000 chars)", summary)
        self.assertIn("- `skill_view` x6, 1.26M total, 41.7K max", summary)
        self.assertIn("- 1 more", summary)
        self.assertIn("**Repeated commands** (6 patterns)", summary)
        self.assertIn("- `patch(('mode', 'patch'))` x8", summary)
        self.assertIn("**Unused skills** (44 of 80, 4,772 / 7,736 catalog chars)", summary)
        self.assertIn("**Domain fit**: domain map unavailable", summary)
        self.assertIn("**Lane ideation**: no lane candidates", summary)
        self.assertIn("**Context churn**: run data unavailable", summary)
        self.assertLessEqual(len(summary), mine_module.DISCORD_MESSAGE_LIMIT)


class UnusedSkillsTest(unittest.TestCase):
    def _make_skills_dir(self, td, skills):
        """Create a temporary skills directory.

        skills: dict of name -> description
        """
        skills_dir = Path(td) / "skills"
        for name, description in skills.items():
            skill_dir = skills_dir / name
            skill_dir.mkdir(parents=True)
            frontmatter = f"---\nname: {name}\ndescription: \"{description}\"\n---\n"
            (skill_dir / "SKILL.md").write_text(frontmatter)
        return skills_dir

    def _make_state_db(self, td, tool_calls_rows):
        """Create a temporary state db with tool_calls rows.

        tool_calls_rows: list of (session_id, msg_id, tool_calls_json)
        """
        db_path = Path(td) / "state.db"
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
        for session_id, msg_id, tc_json in tool_calls_rows:
            conn.execute(
                "INSERT INTO messages (id, session_id, role, tool_calls) VALUES (?, ?, 'assistant', ?)",
                (msg_id, session_id, tc_json),
            )
        conn.commit()
        conn.close()
        return db_path

    def test_detects_used_skill_via_skill_view(self):
        with tempfile.TemporaryDirectory() as td:
            skills_dir = self._make_skills_dir(td, {
                "alpha": "Alpha skill",
                "beta": "Beta skill",
            })
            state_db = self._make_state_db(td, [
                ("s1", 1, json.dumps([{
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "skill_view", "arguments": '{"name": "alpha"}'},
                }])),
            ])

            result = mine_module.mine_unused_skills(
                skills_dir, state_db,
                Path(td) / "profiles",
                Path(td) / "hooks",
                Path(td) / "scripts",
                Path(td) / "boards",
            )

        unused_names = {s["name"] for s in result["skills"]}
        self.assertNotIn("alpha", unused_names)
        self.assertIn("beta", unused_names)

    def test_detects_used_skill_via_skill_manage(self):
        with tempfile.TemporaryDirectory() as td:
            skills_dir = self._make_skills_dir(td, {
                "alpha": "Alpha skill",
                "beta": "Beta skill",
            })
            state_db = self._make_state_db(td, [
                ("s1", 1, json.dumps([{
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "skill_manage",
                        "arguments": '{"operations":[{"name":"alpha","action":"patch","old_string":"x","new_string":"y"}]}',
                    },
                }])),
            ])

            result = mine_module.mine_unused_skills(
                skills_dir, state_db,
                Path(td) / "profiles",
                Path(td) / "hooks",
                Path(td) / "scripts",
                Path(td) / "boards",
            )

        unused_names = {s["name"] for s in result["skills"]}
        self.assertNotIn("alpha", unused_names)
        self.assertIn("beta", unused_names)

    def test_detects_used_skill_via_file_path(self):
        with tempfile.TemporaryDirectory() as td:
            skills_dir = self._make_skills_dir(td, {
                "alpha": "Alpha skill",
                "beta": "Beta skill",
            })
            state_db = self._make_state_db(td, [
                ("s1", 1, json.dumps([{
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": json.dumps({"path": str(skills_dir / "alpha" / "SKILL.md")}),
                    },
                }])),
            ])

            result = mine_module.mine_unused_skills(
                skills_dir, state_db,
                Path(td) / "profiles",
                Path(td) / "hooks",
                Path(td) / "scripts",
                Path(td) / "boards",
            )

        unused_names = {s["name"] for s in result["skills"]}
        self.assertNotIn("alpha", unused_names)
        self.assertIn("beta", unused_names)

    def test_reference_in_hook_excludes(self):
        with tempfile.TemporaryDirectory() as td:
            skills_dir = self._make_skills_dir(td, {
                "alpha": "Alpha skill",
                "beta": "Beta skill",
            })
            hooks_dir = Path(td) / "hooks"
            hooks_dir.mkdir()
            (hooks_dir / "test.sh").write_text("echo alpha")
            state_db = self._make_state_db(td, [])

            result = mine_module.mine_unused_skills(
                skills_dir, state_db,
                Path(td) / "profiles",
                hooks_dir,
                Path(td) / "scripts",
                Path(td) / "boards",
            )

        unused_names = {s["name"] for s in result["skills"]}
        self.assertNotIn("alpha", unused_names)
        self.assertIn("beta", unused_names)

    def test_reference_in_script_excludes(self):
        with tempfile.TemporaryDirectory() as td:
            skills_dir = self._make_skills_dir(td, {
                "alpha": "Alpha skill",
                "beta": "Beta skill",
            })
            scripts_dir = Path(td) / "scripts"
            scripts_dir.mkdir()
            (scripts_dir / "test.py").write_text("# uses alpha")
            state_db = self._make_state_db(td, [])

            result = mine_module.mine_unused_skills(
                skills_dir, state_db,
                Path(td) / "profiles",
                Path(td) / "hooks",
                scripts_dir,
                Path(td) / "boards",
            )

        unused_names = {s["name"] for s in result["skills"]}
        self.assertNotIn("alpha", unused_names)
        self.assertIn("beta", unused_names)

    def test_kanban_skills_pin_excludes(self):
        with tempfile.TemporaryDirectory() as td:
            skills_dir = self._make_skills_dir(td, {
                "alpha": "Alpha skill",
                "beta": "Beta skill",
            })
            boards_dir = Path(td) / "boards"
            board_dir = boards_dir / "test"
            board_dir.mkdir(parents=True)
            db_path = board_dir / "kanban.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    body TEXT,
                    assignee TEXT,
                    status TEXT,
                    skills TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO tasks (id, title, status, skills) VALUES (?, ?, ?, ?)",
                ("t1", "test", "running", json.dumps(["alpha"])),
            )
            conn.commit()
            conn.close()
            state_db = self._make_state_db(td, [])

            result = mine_module.mine_unused_skills(
                skills_dir, state_db,
                Path(td) / "profiles",
                Path(td) / "hooks",
                Path(td) / "scripts",
                boards_dir,
            )

        unused_names = {s["name"] for s in result["skills"]}
        self.assertNotIn("alpha", unused_names)
        self.assertIn("beta", unused_names)

    def test_profile_db_aggregation(self):
        with tempfile.TemporaryDirectory() as td:
            skills_dir = self._make_skills_dir(td, {
                "alpha": "Alpha skill",
                "beta": "Beta skill",
            })
            state_db = self._make_state_db(td, [])
            profiles_dir = Path(td) / "profiles"
            profile_dir = profiles_dir / "test"
            profile_dir.mkdir(parents=True)
            profile_db = profile_dir / "state.db"
            conn = sqlite3.connect(profile_db)
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
            conn.execute(
                "INSERT INTO messages (id, session_id, role, tool_calls) VALUES (?, ?, 'assistant', ?)",
                (1, "s1", json.dumps([{
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "skill_view", "arguments": '{"name": "alpha"}'},
                }])),
            )
            conn.commit()
            conn.close()

            result = mine_module.mine_unused_skills(
                skills_dir, state_db,
                profiles_dir,
                Path(td) / "hooks",
                Path(td) / "scripts",
                Path(td) / "boards",
            )

        unused_names = {s["name"] for s in result["skills"]}
        self.assertNotIn("alpha", unused_names)
        self.assertIn("beta", unused_names)

    def test_keep_list_skips_prune(self):
        with tempfile.TemporaryDirectory() as td:
            skills_dir = self._make_skills_dir(td, {
                "alpha": "Alpha skill",
            })
            state_db = self._make_state_db(td, [])

            # Temporarily add alpha to KEEP_LIST
            original_keep = set(mine_module.KEEP_LIST)
            mine_module.KEEP_LIST.add("alpha")
            try:
                result = mine_module.mine_unused_skills(
                    skills_dir, state_db,
                    Path(td) / "profiles",
                    Path(td) / "hooks",
                    Path(td) / "scripts",
                    Path(td) / "boards",
                )
            finally:
                mine_module.KEEP_LIST.clear()
                mine_module.KEEP_LIST.update(original_keep)

        unused_names = {s["name"] for s in result["skills"]}
        self.assertNotIn("alpha", unused_names)
        keep_names = {k["name"] for k in result["keep_list"]}
        self.assertIn("alpha", keep_names)

    def test_counts_and_costs(self):
        with tempfile.TemporaryDirectory() as td:
            skills_dir = self._make_skills_dir(td, {
                "alpha": "Alpha skill",
                "beta": "Beta skill",
            })
            state_db = self._make_state_db(td, [])

            result = mine_module.mine_unused_skills(
                skills_dir, state_db,
                Path(td) / "profiles",
                Path(td) / "hooks",
                Path(td) / "scripts",
                Path(td) / "boards",
            )

        self.assertEqual(result["total_skills"], 2)
        self.assertEqual(result["never_used_count"], 2)
        self.assertEqual(result["used_count"], 0)
        self.assertTrue(result["total_catalog_cost"] > 0)
        self.assertTrue(result["never_used_cost"] > 0)


class DomainFitTest(unittest.TestCase):
    def _make_domain_map(self, td, domains):
        """Create a temporary domain map YAML.

        domains: dict of domain_name -> {"profiles": [...], "skills": [...], "signals": [...]}
        """
        map_path = Path(td) / "domain-map.yaml"
        data = {"version": 1, "domains": {}}
        for name, info in domains.items():
            data["domains"][name] = {
                "profiles": info.get("profiles", []),
                "skills": info.get("skills", []),
                "signals": info.get("signals", []),
            }
        # JSON is valid for both PyYAML and the stdlib subset parser.
        map_path.write_text(json.dumps(data, indent=2))
        return map_path

    def _make_state_db(self, td, tool_calls_rows):
        """Create a temporary state db with tool_calls rows."""
        db_path = Path(td) / "state.db"
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
        for session_id, msg_id, tc_json in tool_calls_rows:
            conn.execute(
                "INSERT INTO messages (id, session_id, role, tool_calls) VALUES (?, ?, 'assistant', ?)",
                (msg_id, session_id, tc_json),
            )
        conn.commit()
        conn.close()
        return db_path

    def _make_skills_dir(self, td, skills):
        skills_dir = Path(td) / "skills"
        for name, description in skills.items():
            skill_dir = skills_dir / name
            skill_dir.mkdir(parents=True)
            frontmatter = f"---\nname: {name}\ndescription: \"{description}\"\n---\n"
            (skill_dir / "SKILL.md").write_text(frontmatter)
        return skills_dir

    def test_cross_domain_skill_use_detected(self):
        with tempfile.TemporaryDirectory() as td:
            map_path = self._make_domain_map(td, {
                "product": {"profiles": ["scribe"], "skills": ["alpha"], "signals": []},
                "infra": {"profiles": [], "skills": ["beta"], "signals": []},
            })
            skills_dir = self._make_skills_dir(td, {"alpha": "A", "beta": "B"})
            state_db = self._make_state_db(td, [
                ("s1", 1, json.dumps([{
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "skill_view", "arguments": '{"name": "beta"}'},
                }])),
            ])
            profiles_dir = Path(td) / "profiles"
            profile_dir = profiles_dir / "scribe"
            profile_dir.mkdir(parents=True)
            profile_db = profile_dir / "state.db"
            import shutil
            shutil.copy(state_db, profile_db)

            result = mine_module.mine_domain_fit(
                map_path, skills_dir, state_db, profiles_dir, Path(td) / "boards"
            )

        self.assertIsNone(result["note"])
        scribe = next(p for p in result["profiles"] if p["profile"] == "scribe")
        self.assertEqual(len(scribe["cross_domain_skill_use"]), 1)
        self.assertEqual(scribe["cross_domain_skill_use"][0]["skill"], "beta")
        self.assertEqual(scribe["cross_domain_skill_use"][0]["skill_domain"], "infra")

    def test_signal_matching_in_terminal_history(self):
        with tempfile.TemporaryDirectory() as td:
            map_path = self._make_domain_map(td, {
                "product": {"profiles": ["scribe"], "skills": [], "signals": []},
                "infra": {"profiles": [], "skills": [], "signals": [r"\bwrangler\b"]},
            })
            skills_dir = self._make_skills_dir(td, {})
            state_db = self._make_state_db(td, [
                ("s1", 1, json.dumps([{
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "terminal", "arguments": '{"command": "wrangler deploy"}'},
                }])),
            ])
            profiles_dir = Path(td) / "profiles"
            profile_dir = profiles_dir / "scribe"
            profile_dir.mkdir(parents=True)
            profile_db = profile_dir / "state.db"
            import shutil
            shutil.copy(state_db, profile_db)

            result = mine_module.mine_domain_fit(
                map_path, skills_dir, state_db, profiles_dir, Path(td) / "boards"
            )

        scribe = next(p for p in result["profiles"] if p["profile"] == "scribe")
        self.assertIn("infra", scribe["cross_domain_signals"])
        self.assertEqual(len(scribe["cross_domain_signals"]["infra"]), 1)
        self.assertEqual(scribe["cross_domain_signals"]["infra"][0]["command"], "wrangler deploy")

    def test_routing_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            map_path = self._make_domain_map(td, {
                "product": {"profiles": ["scribe"], "skills": [], "signals": [r"acme-app"]},
                "review": {"profiles": ["jester"], "skills": [], "signals": []},
            })
            skills_dir = self._make_skills_dir(td, {})
            state_db = self._make_state_db(td, [])
            boards_dir = Path(td) / "boards"
            board_dir = boards_dir / "test"
            board_dir.mkdir(parents=True)
            db_path = board_dir / "kanban.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    body TEXT,
                    assignee TEXT,
                    status TEXT,
                    skills TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO tasks (id, title, body, assignee, status) VALUES (?, ?, ?, ?, ?)",
                ("t1", "Fix acme-app build", "Body", "jester", "running"),
            )
            conn.commit()
            conn.close()

            result = mine_module.mine_domain_fit(
                map_path, skills_dir, state_db, Path(td) / "profiles", boards_dir
            )

        # Review-lane assignments are skipped; jester is review domain.
        self.assertEqual(len(result["routing_mismatches"]), 0)

    def test_unassigned_domain_pressure_ranking(self):
        with tempfile.TemporaryDirectory() as td:
            map_path = self._make_domain_map(td, {
                "product": {"profiles": ["scribe"], "skills": [], "signals": []},
                "infra": {"profiles": [], "skills": [], "signals": [r"\bwrangler\b"]},
                "home": {"profiles": [], "skills": [], "signals": [r"\bchezmoi\b"]},
            })
            skills_dir = self._make_skills_dir(td, {})
            state_db = self._make_state_db(td, [
                ("s1", 1, json.dumps([{
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "terminal", "arguments": '{"command": "wrangler deploy"}'},
                }])),
                ("s1", 2, json.dumps([{
                    "id": "c2",
                    "type": "function",
                    "function": {"name": "terminal", "arguments": '{"command": "chezmoi apply"}'},
                }])),
                ("s1", 3, json.dumps([{
                    "id": "c3",
                    "type": "function",
                    "function": {"name": "terminal", "arguments": '{"command": "wrangler tail"}'},
                }])),
            ])
            profiles_dir = Path(td) / "profiles"
            profile_dir = profiles_dir / "scribe"
            profile_dir.mkdir(parents=True)
            profile_db = profile_dir / "state.db"
            # Create empty profile db so pressure comes only from default state db
            conn = sqlite3.connect(profile_db)
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
            conn.commit()
            conn.close()

            result = mine_module.mine_domain_fit(
                map_path, skills_dir, state_db, profiles_dir, Path(td) / "boards"
            )

        pressure = result["domain_pressure"]
        self.assertEqual(len(pressure), 2)
        self.assertEqual(pressure[0]["domain"], "infra")
        self.assertEqual(pressure[0]["hits"], 2)
        self.assertEqual(pressure[1]["domain"], "home")
        self.assertEqual(pressure[1]["hits"], 1)

    def test_missing_map_handled_gracefully(self):
        with tempfile.TemporaryDirectory() as td:
            map_path = Path(td) / "missing.yaml"
            skills_dir = self._make_skills_dir(td, {})
            state_db = self._make_state_db(td, [])

            result = mine_module.mine_domain_fit(
                map_path, skills_dir, state_db, Path(td) / "profiles", Path(td) / "boards"
            )

        self.assertIn("not found", result["note"])
        self.assertEqual(result["profiles"], [])
        self.assertEqual(result["domain_pressure"], [])

    def test_generalist_never_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            map_path = self._make_domain_map(td, {
                "product": {"profiles": ["scribe"], "skills": ["alpha"], "signals": []},
            })
            skills_dir = self._make_skills_dir(td, {"alpha": "A", "beta": "B"})
            state_db = self._make_state_db(td, [
                ("s1", 1, json.dumps([{
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "skill_view", "arguments": '{"name": "alpha"}'},
                }])),
            ])
            profiles_dir = Path(td) / "profiles"
            generalist_dir = profiles_dir / "generalist"
            generalist_dir.mkdir(parents=True)
            generalist_db = generalist_dir / "state.db"
            import shutil
            shutil.copy(state_db, generalist_db)

            result = mine_module.mine_domain_fit(
                map_path, skills_dir, state_db, profiles_dir, Path(td) / "boards"
            )

        gen = next(p for p in result["profiles"] if p["profile"] == "generalist")
        self.assertIsNone(gen["domain"])
        self.assertEqual(len(gen["cross_domain_skill_use"]), 0)
        self.assertEqual(len(gen["cross_domain_signals"]), 0)

    def test_generalist_domain_never_flagged(self):
        """default mapped to generalist domain must not be flagged (regression)."""
        with tempfile.TemporaryDirectory() as td:
            map_path = self._make_domain_map(td, {
                "product": {"profiles": ["scribe"], "skills": ["alpha"], "signals": []},
                "generalist": {"profiles": ["default"], "skills": [], "signals": []},
            })
            skills_dir = self._make_skills_dir(td, {"alpha": "A", "beta": "B"})
            state_db = self._make_state_db(td, [
                ("s1", 1, json.dumps([{
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "skill_view", "arguments": '{"name": "alpha"}'},
                }])),
                ("s1", 2, json.dumps([{
                    "id": "c2",
                    "type": "function",
                    "function": {"name": "terminal", "arguments": '{"command": "npm test"}'},
                }])),
            ])
            profiles_dir = Path(td) / "profiles"

            result = mine_module.mine_domain_fit(
                map_path, skills_dir, state_db, profiles_dir, Path(td) / "boards"
            )

        default = next(p for p in result["profiles"] if p["profile"] == "default")
        self.assertEqual(default["domain"], "generalist")
        self.assertEqual(len(default["cross_domain_skill_use"]), 0)
        self.assertEqual(len(default["cross_domain_signals"]), 0)

    def test_shared_domain_skill_use_not_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            map_path = self._make_domain_map(td, {
                "product": {"profiles": ["scribe"], "skills": ["alpha"], "signals": []},
                "shared": {"profiles": [], "skills": ["humanizer"], "signals": []},
            })
            skills_dir = self._make_skills_dir(td, {"alpha": "A", "humanizer": "H"})
            state_db = self._make_state_db(td, [
                ("s1", 1, json.dumps([{
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "skill_view", "arguments": '{"name": "humanizer"}'},
                }])),
            ])
            profiles_dir = Path(td) / "profiles"
            profile_dir = profiles_dir / "scribe"
            profile_dir.mkdir(parents=True)
            profile_db = profile_dir / "state.db"
            import shutil
            shutil.copy(state_db, profile_db)

            result = mine_module.mine_domain_fit(
                map_path, skills_dir, state_db, profiles_dir, Path(td) / "boards"
            )

        scribe = next(p for p in result["profiles"] if p["profile"] == "scribe")
        self.assertEqual(len(scribe["cross_domain_skill_use"]), 0)

    def test_shared_domain_signals_not_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            map_path = self._make_domain_map(td, {
                "product": {"profiles": ["scribe"], "skills": [], "signals": []},
                "shared": {"profiles": [], "skills": [], "signals": [r"\bhumanizer\b"]},
            })
            skills_dir = self._make_skills_dir(td, {})
            state_db = self._make_state_db(td, [
                ("s1", 1, json.dumps([{
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "terminal", "arguments": '{"command": "humanizer fix"}'},
                }])),
            ])
            profiles_dir = Path(td) / "profiles"
            profile_dir = profiles_dir / "scribe"
            profile_dir.mkdir(parents=True)
            profile_db = profile_dir / "state.db"
            import shutil
            shutil.copy(state_db, profile_db)

            result = mine_module.mine_domain_fit(
                map_path, skills_dir, state_db, profiles_dir, Path(td) / "boards"
            )

        scribe = next(p for p in result["profiles"] if p["profile"] == "scribe")
        self.assertNotIn("shared", scribe["cross_domain_signals"])

    def test_review_routing_mismatch_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            map_path = self._make_domain_map(td, {
                "product": {"profiles": ["scribe"], "skills": [], "signals": [r"acme-app"]},
                "review": {"profiles": ["jester"], "skills": [], "signals": []},
            })
            skills_dir = self._make_skills_dir(td, {})
            state_db = self._make_state_db(td, [])
            boards_dir = Path(td) / "boards"
            board_dir = boards_dir / "test"
            board_dir.mkdir(parents=True)
            db_path = board_dir / "kanban.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    body TEXT,
                    assignee TEXT,
                    status TEXT,
                    skills TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO tasks (id, title, body, assignee, status) VALUES (?, ?, ?, ?, ?)",
                ("t1", "Fix acme-app build", "Body", "jester", "running"),
            )
            conn.commit()
            conn.close()

            result = mine_module.mine_domain_fit(
                map_path, skills_dir, state_db, Path(td) / "profiles", boards_dir
            )

        self.assertEqual(len(result["routing_mismatches"]), 0)

    def test_non_review_routing_mismatch_still_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            map_path = self._make_domain_map(td, {
                "product": {"profiles": ["scribe"], "skills": [], "signals": []},
                "review": {"profiles": ["jester"], "skills": [], "signals": [r"\bgh pr review\b"]},
            })
            skills_dir = self._make_skills_dir(td, {})
            state_db = self._make_state_db(td, [])
            boards_dir = Path(td) / "boards"
            board_dir = boards_dir / "test"
            board_dir.mkdir(parents=True)
            db_path = board_dir / "kanban.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    body TEXT,
                    assignee TEXT,
                    status TEXT,
                    skills TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO tasks (id, title, body, assignee, status) VALUES (?, ?, ?, ?, ?)",
                ("t1", "gh pr review for foo", "Body", "scribe", "running"),
            )
            conn.commit()
            conn.close()

            result = mine_module.mine_domain_fit(
                map_path, skills_dir, state_db, Path(td) / "profiles", boards_dir
            )

        self.assertEqual(len(result["routing_mismatches"]), 1)
        self.assertEqual(result["routing_mismatches"][0]["task_id"], "t1")
        self.assertEqual(result["routing_mismatches"][0]["matched_domain"], "review")
        self.assertEqual(result["routing_mismatches"][0]["assignee"], "scribe")

    def test_archived_card_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            map_path = self._make_domain_map(td, {
                "product": {"profiles": ["scribe"], "skills": [], "signals": [r"acme-app"]},
            })
            skills_dir = self._make_skills_dir(td, {})
            state_db = self._make_state_db(td, [])
            boards_dir = Path(td) / "boards"
            board_dir = boards_dir / "test"
            board_dir.mkdir(parents=True)
            db_path = board_dir / "kanban.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    body TEXT,
                    assignee TEXT,
                    status TEXT,
                    skills TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO tasks (id, title, body, assignee, status) VALUES (?, ?, ?, ?, ?)",
                ("t1", "Fix acme-app build", "Body", "jester", "archived"),
            )
            conn.commit()
            conn.close()

            result = mine_module.mine_domain_fit(
                map_path, skills_dir, state_db, Path(td) / "profiles", boards_dir
            )

        self.assertEqual(len(result["routing_mismatches"]), 0)

    def test_done_card_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            map_path = self._make_domain_map(td, {
                "product": {"profiles": ["scribe"], "skills": [], "signals": [r"acme-app"]},
            })
            skills_dir = self._make_skills_dir(td, {})
            state_db = self._make_state_db(td, [])
            boards_dir = Path(td) / "boards"
            board_dir = boards_dir / "test"
            board_dir.mkdir(parents=True)
            db_path = board_dir / "kanban.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    body TEXT,
                    assignee TEXT,
                    status TEXT,
                    skills TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO tasks (id, title, body, assignee, status) VALUES (?, ?, ?, ?, ?)",
                ("t1", "Fix acme-app build", "Body", "jester", "done"),
            )
            conn.commit()
            conn.close()

            result = mine_module.mine_domain_fit(
                map_path, skills_dir, state_db, Path(td) / "profiles", boards_dir
            )

        self.assertEqual(len(result["routing_mismatches"]), 0)

    def test_unmapped_assignee_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            map_path = self._make_domain_map(td, {
                "product": {"profiles": ["scribe"], "skills": [], "signals": [r"acme-app"]},
            })
            skills_dir = self._make_skills_dir(td, {})
            state_db = self._make_state_db(td, [])
            boards_dir = Path(td) / "boards"
            board_dir = boards_dir / "test"
            board_dir.mkdir(parents=True)
            db_path = board_dir / "kanban.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    body TEXT,
                    assignee TEXT,
                    status TEXT,
                    skills TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO tasks (id, title, body, assignee, status) VALUES (?, ?, ?, ?, ?)",
                ("t1", "Fix acme-app build", "Body", "tom", "running"),
            )
            conn.commit()
            conn.close()

            result = mine_module.mine_domain_fit(
                map_path, skills_dir, state_db, Path(td) / "profiles", boards_dir
            )

        self.assertEqual(len(result["routing_mismatches"]), 0)

    def test_generalist_assignee_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            map_path = self._make_domain_map(td, {
                "product": {"profiles": ["scribe"], "skills": [], "signals": [r"acme-app"]},
                "generalist": {"profiles": ["default"], "skills": [], "signals": []},
            })
            skills_dir = self._make_skills_dir(td, {})
            state_db = self._make_state_db(td, [])
            boards_dir = Path(td) / "boards"
            board_dir = boards_dir / "test"
            board_dir.mkdir(parents=True)
            db_path = board_dir / "kanban.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    body TEXT,
                    assignee TEXT,
                    status TEXT,
                    skills TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO tasks (id, title, body, assignee, status) VALUES (?, ?, ?, ?, ?)",
                ("t1", "Fix acme-app build", "Body", "default", "running"),
            )
            conn.commit()
            conn.close()

            result = mine_module.mine_domain_fit(
                map_path, skills_dir, state_db, Path(td) / "profiles", boards_dir
            )

        self.assertEqual(len(result["routing_mismatches"]), 0)

    def test_multi_domain_match_collapses_to_strongest(self):
        with tempfile.TemporaryDirectory() as td:
            map_path = self._make_domain_map(td, {
                "product": {"profiles": ["scribe"], "skills": [], "signals": [r"acme-app", r"npm"]},
                "home": {"profiles": [], "skills": [], "signals": [r"chezmoi"]},
                "investigate": {"profiles": ["page"], "skills": [], "signals": []},
            })
            skills_dir = self._make_skills_dir(td, {})
            state_db = self._make_state_db(td, [])
            boards_dir = Path(td) / "boards"
            board_dir = boards_dir / "test"
            board_dir.mkdir(parents=True)
            db_path = board_dir / "kanban.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    body TEXT,
                    assignee TEXT,
                    status TEXT,
                    skills TEXT
                )
                """
            )
            # product has 2 hits, home has 1 hit.
            conn.execute(
                "INSERT INTO tasks (id, title, body, assignee, status) VALUES (?, ?, ?, ?, ?)",
                ("t1", "acme-app npm and chezmoi", "Body", "page", "running"),
            )
            conn.commit()
            conn.close()

            result = mine_module.mine_domain_fit(
                map_path, skills_dir, state_db, Path(td) / "profiles", boards_dir
            )

        self.assertEqual(len(result["routing_mismatches"]), 1)
        self.assertEqual(result["routing_mismatches"][0]["task_id"], "t1")
        self.assertEqual(result["routing_mismatches"][0]["matched_domain"], "product")
        self.assertEqual(result["routing_mismatches"][0]["other_matches"], 1)

    def test_profile_db_aggregation_includes_default(self):
        with tempfile.TemporaryDirectory() as td:
            map_path = self._make_domain_map(td, {
                "product": {"profiles": ["scribe"], "skills": ["alpha"], "signals": []},
            })
            skills_dir = self._make_skills_dir(td, {"alpha": "A"})
            state_db = self._make_state_db(td, [])
            profiles_dir = Path(td) / "profiles"
            profile_dir = profiles_dir / "scribe"
            profile_dir.mkdir(parents=True)
            profile_db = profile_dir / "state.db"
            import shutil
            shutil.copy(state_db, profile_db)

            result = mine_module.mine_domain_fit(
                map_path, skills_dir, state_db, profiles_dir, Path(td) / "boards"
            )

        profile_names = {p["profile"] for p in result["profiles"]}
        self.assertIn("default", profile_names)
        self.assertIn("scribe", profile_names)


class ContextChurnTest(unittest.TestCase):
    def _make_session_db(self, db_path, sessions, messages):
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE sessions ("
            " id TEXT PRIMARY KEY, source TEXT,"
            " input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,"
            " cache_read_tokens INTEGER DEFAULT 0, cache_write_tokens INTEGER DEFAULT 0)"
        )
        conn.execute(
            "CREATE TABLE messages ("
            " id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,"
            " content TEXT, tool_name TEXT)"
        )
        conn.executemany("INSERT INTO sessions VALUES (?,?,?,?,?,?)", sessions)
        conn.executemany("INSERT INTO messages VALUES (?,?,?,?,?)", messages)
        conn.commit()
        conn.close()
        return db_path

    def _make_board(self, boards_dir, board="acme"):
        board_dir = Path(boards_dir) / board
        board_dir.mkdir(parents=True)
        conn = sqlite3.connect(board_dir / "kanban.db")
        conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT)")
        conn.execute("INSERT INTO tasks VALUES ('t_aaa', 'Churned card')")
        conn.execute("INSERT INTO tasks VALUES ('t_bbb', 'Quiet card')")
        conn.commit()
        conn.close()

    def _fixture(self, td):
        profiles_dir = Path(td) / "profiles"
        scribe = profiles_dir / "scribe"
        scribe.mkdir(parents=True)
        sessions = [
            # three runs of the same card: churned
            ("w1", "kanban", 100_000, 1_000, 3_000_000, 50_000),
            ("w2", "kanban", 100_000, 1_000, 3_000_000, 50_000),
            ("w3", "kanban", 100_000, 1_000, 3_000_000, 50_000),
            # one run of another card: quiet
            ("w4", "kanban", 10_000, 5_000, 100_000, 0),
        ]
        messages = [
            (1, "w1", "user", "work kanban task t_aaa", None),
            (2, "w1", "tool", "card body", "kanban_show"),
            (3, "w1", "tool", "card body again", "kanban_show"),
            (4, "w2", "user", "work kanban task t_aaa", None),
            (5, "w3", "user", "work kanban task t_aaa", None),
            (6, "w4", "user", "work kanban task t_bbb", None),
            (7, "w4", "tool", "card body", "kanban_show"),
        ]
        db = self._make_session_db(scribe / "state.db", sessions, messages)
        boards_dir = Path(td) / "boards"
        self._make_board(boards_dir)
        return profiles_dir, boards_dir

    def test_groups_runs_into_cards_and_flags_churn(self):
        with tempfile.TemporaryDirectory() as td:
            profiles_dir, boards_dir = self._fixture(td)
            result = mine_module.mine_context_churn(
                Path(td) / "missing.db", profiles_dir, boards_dir
            )
        self.assertIsNone(result["note"])
        self.assertEqual(result["kanban_sessions"], 4)
        self.assertEqual(result["cards_seen"], 2)
        mr = result["multi_run"]
        self.assertEqual(mr["cards"], 1)
        top = mr["top_cards"][0]
        self.assertEqual(top["task_id"], "t_aaa")
        self.assertEqual(top["runs"], 3)
        self.assertEqual(top["title"], "Churned card")
        self.assertEqual(top["board"], "acme")
        # t_aaa holds 9.45M of 9.56M card tokens
        self.assertGreater(mr["token_share_pct"], 95)
        self.assertTrue(any("triage" in p for p in result["proposals"]))

    def test_counts_kanban_show_refetch(self):
        with tempfile.TemporaryDirectory() as td:
            profiles_dir, boards_dir = self._fixture(td)
            result = mine_module.mine_context_churn(
                Path(td) / "missing.db", profiles_dir, boards_dir
            )
        ks = result["kanban_show_refetch"]
        self.assertEqual(ks["calls"], 3)  # two in w1, one in w4
        self.assertEqual(ks["sessions_with_multiple"], 1)
        self.assertGreater(ks["approx_tokens"], 0)

    def test_flags_amplified_sessions(self):
        with tempfile.TemporaryDirectory() as td:
            profiles_dir, boards_dir = self._fixture(td)
            result = mine_module.mine_context_churn(
                Path(td) / "missing.db", profiles_dir, boards_dir
            )
        amp = result["amplification"]
        self.assertEqual(amp["sessions_above"], 3)  # the three 3.15M-in / 1K-out runs
        self.assertEqual(amp["worst_sessions"][0]["session_id"], "w1")
        self.assertGreater(amp["median_ratio"], 0)

    def test_note_when_no_dbs_readable(self):
        with tempfile.TemporaryDirectory() as td:
            result = mine_module.mine_context_churn(
                Path(td) / "missing.db", Path(td) / "no-profiles", Path(td) / "no-boards"
            )
        self.assertEqual(result["note"], "no readable state dbs found")
        self.assertEqual(result["proposals"], [])


class YamlSubsetLoadTest(unittest.TestCase):
    def test_default_map_is_user_config(self):
        with unittest.mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": "/cfg"}):
            self.assertEqual(mine_module._default_domain_map(), Path("/cfg/clearstack/domain-map.yaml"))
        with unittest.mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": ""}):
            self.assertEqual(
                mine_module._default_domain_map(), Path.home() / ".config" / "clearstack" / "domain-map.yaml"
            )

    def test_parses_the_example_domain_map(self):
        text = (MINE.parents[3] / "skills" / "clear-reflect" / "references" / "domain-map.example.yaml").read_text()
        data = mine_module._yaml_subset_load(text)
        self.assertEqual(data["version"], 1)
        domains = data["domains"]
        for name in ("product", "review", "investigate", "orchestration", "infra", "home", "shared", "generalist"):
            self.assertIn(name, domains)
        self.assertIn("scribe", domains["product"]["profiles"])
        self.assertIn("github", domains["product"]["skills"])
        self.assertEqual(domains["generalist"]["skills"], [])
        self.assertEqual(domains["generalist"]["signals"], [])
        self.assertTrue(any("npm" in s for s in domains["product"]["signals"]))

    def test_safe_load_falls_back_without_pyyaml(self):
        text = (MINE.parents[3] / "skills" / "clear-reflect" / "references" / "domain-map.example.yaml").read_text()
        saved = mine_module.yaml
        try:
            mine_module.yaml = None
            data = mine_module._yaml_safe_load(text)
        finally:
            mine_module.yaml = saved
        self.assertIn("domains", data)
