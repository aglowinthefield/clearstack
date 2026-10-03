"""Tests for the lane-ideation detector.

Covers each gate independently, a two-window recurrent cluster, a one-week
cluster rejection, a well-placed cluster rejection, and empty/missing dbs.
"""

import json
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# lane_ideation.py lives in ../scripts
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import lane_ideation as li


class TestLaneIdeation(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"
        self._create_schema(self.db_path)
        self.domain_map = {
            "domains": {
                "product": {
                    "profiles": ["scribe"],
                    "skills": {"github", "silk-agent-map"},
                    "signals": [re.compile(r"\bnpm\b")],
                },
                "investigate": {
                    "profiles": ["page"],
                    "skills": {"grounded-citations"},
                    "signals": [re.compile(r"\bcurl\b")],
                },
                "infra": {
                    "profiles": [],
                    "skills": {"wrangler"},
                    "signals": [re.compile(r"\bwrangler\b")],
                },
            },
            "profile_domain": {"scribe": "product", "page": "investigate"},
            "assigned_profiles": {"scribe", "page"},
        }

    def tearDown(self):
        self.tmpdir.cleanup()

    def _create_schema(self, path):
        conn = sqlite3.connect(path)
        conn.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                profile_name TEXT,
                git_repo_root TEXT,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                tool_calls TEXT,
                timestamp REAL
            )
            """
        )
        conn.close()

    def _insert_session(self, sid, profile, repo="", input_tokens=0, output_tokens=0):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO sessions (id, profile_name, git_repo_root, input_tokens, output_tokens) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, profile, repo, input_tokens, output_tokens),
        )
        conn.commit()
        conn.close()

    def _insert_message(self, sid, role, tool_calls, timestamp):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO messages (session_id, role, tool_calls, timestamp) VALUES (?, ?, ?, ?)",
            (sid, role, json.dumps(tool_calls) if isinstance(tool_calls, list) else tool_calls, timestamp),
        )
        conn.commit()
        conn.close()

    def _make_terminal_call(self, command):
        return [
            {
                "id": "call-1",
                "function": {
                    "name": "terminal",
                    "arguments": json.dumps({"command": command}),
                },
            }
        ]

    def _make_skill_call(self, skill_name):
        return [
            {
                "id": "call-1",
                "function": {
                    "name": "skill_view",
                    "arguments": json.dumps({"name": skill_name}),
                },
            }
        ]

    def test_empty_db(self):
        """Empty db returns no candidates."""
        result = li.mine_lane_ideation(self.domain_map, self.db_path, Path("/nonexistent"))
        self.assertEqual(result["candidate_count"], 0)
        self.assertIn("no sessions", result["note"])

    def test_missing_db(self):
        """Missing db is handled gracefully."""
        result = li.mine_lane_ideation(self.domain_map, Path("/no/such/db"), Path("/no/profiles"))
        self.assertEqual(result["candidate_count"], 0)

    def test_coherence_rejects_scattered_sessions(self):
        """A cluster with no dominant signal fails the coherent gate."""
        for i in range(5):
            sid = f"sess-{i}"
            self._insert_session(sid, "page")
            # Each session uses a different binary
            self._insert_message(
                sid, "assistant", self._make_terminal_call(f"cmd{i}"), i * 86400.0
            )
        result = li.mine_lane_ideation(self.domain_map, self.db_path, Path("/nonexistent"))
        self.assertEqual(result["candidate_count"], 0)

    def test_volume_rejects_small_cluster(self):
        """A cluster with only 2 sessions fails the volume gate."""
        for i in range(2):
            sid = f"sess-{i}"
            self._insert_session(sid, "page")
            self._insert_message(
                sid, "assistant", self._make_terminal_call("docker ps"), i * 86400.0 * 8
            )
        result = li.mine_lane_ideation(self.domain_map, self.db_path, Path("/nonexistent"))
        self.assertEqual(result["candidate_count"], 0)

    def test_recurrence_rejects_one_week_cluster(self):
        """A coherent cluster confined to one weekly window is rejected."""
        for i in range(5):
            sid = f"sess-{i}"
            self._insert_session(sid, "page")
            self._insert_message(
                sid, "assistant", self._make_terminal_call("docker ps"), i * 3600.0
            )
        result = li.mine_lane_ideation(self.domain_map, self.db_path, Path("/nonexistent"))
        self.assertEqual(result["candidate_count"], 0)

    def test_well_placed_cluster_rejected(self):
        """A cluster whose sessions run in the matching domain is not a candidate."""
        for i in range(5):
            sid = f"sess-{i}"
            self._insert_session(sid, "scribe")
            self._insert_message(
                sid, "assistant", self._make_terminal_call("npm test"), i * 86400.0 * 8
            )
        result = li.mine_lane_ideation(self.domain_map, self.db_path, Path("/nonexistent"))
        self.assertEqual(result["candidate_count"], 0)

    def test_two_window_recurrent_cluster_detected(self):
        """A coherent, recurrent, volume-sufficient, misplaced cluster is reported."""
        # 3 sessions in week 0, 2 in week 1, all page profile, all docker
        for i in range(3):
            sid = f"w0-{i}"
            self._insert_session(sid, "page")
            self._insert_message(
                sid, "assistant", self._make_terminal_call("docker ps"), i * 3600.0
            )
        for i in range(2):
            sid = f"w1-{i}"
            self._insert_session(sid, "page")
            self._insert_message(
                sid, "assistant", self._make_terminal_call("docker ps"), 86400.0 * 8 + i * 3600.0
            )
        # Add noise so docker is not ubiquitous
        for i in range(5):
            sid = f"noise-{i}"
            self._insert_session(sid, "page")
            self._insert_message(
                sid, "assistant", self._make_terminal_call(f"curl {i}"), i * 3600.0
            )
        result = li.mine_lane_ideation(self.domain_map, self.db_path, Path("/nonexistent"))
        self.assertEqual(result["candidate_count"], 1)
        c = result["candidates"][0]
        self.assertEqual(c["session_count"], 5)
        self.assertEqual(c["profiles"], ["page"])
        self.assertIn("bin:docker", c["dominant_signals"])
        self.assertIsNone(c["inferred_domain"])

    def test_misplaced_infra_cluster_detected(self):
        """A cluster matching an unassigned domain (infra) is reported as misplaced."""
        for i in range(3):
            sid = f"w0-{i}"
            self._insert_session(sid, "page")
            self._insert_message(
                sid, "assistant", self._make_terminal_call("wrangler deploy"), i * 3600.0
            )
        for i in range(2):
            sid = f"w1-{i}"
            self._insert_session(sid, "page")
            self._insert_message(
                sid, "assistant", self._make_terminal_call("wrangler deploy"), 86400.0 * 8 + i * 3600.0
            )
        # Add noise so wrangler is not ubiquitous
        for i in range(5):
            sid = f"noise-{i}"
            self._insert_session(sid, "page")
            self._insert_message(
                sid, "assistant", self._make_terminal_call(f"curl {i}"), i * 3600.0
            )
        result = li.mine_lane_ideation(self.domain_map, self.db_path, Path("/nonexistent"))
        self.assertEqual(result["candidate_count"], 1)
        c = result["candidates"][0]
        self.assertEqual(c["inferred_domain"], "infra")

    def test_profile_dbs_are_scanned(self):
        """Sessions from profile dbs are included in clustering."""
        profile_dir = Path(self.tmpdir.name) / "profiles" / "page"
        profile_dir.mkdir(parents=True)
        profile_db = profile_dir / "state.db"
        self._create_schema(profile_db)

        conn = sqlite3.connect(profile_db)
        conn.execute(
            "INSERT INTO sessions (id, profile_name, git_repo_root, input_tokens, output_tokens) "
            "VALUES (?, ?, ?, ?, ?)",
            ("p-sess", "page", "", 100, 100),
        )
        conn.execute(
            "INSERT INTO messages (session_id, role, tool_calls, timestamp) VALUES (?, ?, ?, ?)",
            (
                "p-sess",
                "assistant",
                json.dumps(self._make_terminal_call("docker ps")),
                86400.0 * 8,
            ),
        )
        conn.commit()
        conn.close()

        # Default db also has sessions
        for i in range(3):
            sid = f"w0-{i}"
            self._insert_session(sid, "page")
            self._insert_message(
                sid, "assistant", self._make_terminal_call("docker ps"), i * 3600.0
            )
        # Add noise so docker is not ubiquitous
        for i in range(5):
            sid = f"noise-{i}"
            self._insert_session(sid, "page")
            self._insert_message(
                sid, "assistant", self._make_terminal_call(f"curl {i}"), i * 3600.0
            )

        result = li.mine_lane_ideation(
            self.domain_map, self.db_path, Path(self.tmpdir.name) / "profiles"
        )
        self.assertEqual(result["candidate_count"], 1)
        c = result["candidates"][0]
        self.assertEqual(c["session_count"], 4)

    def test_stoplist_prevents_shell_noise_candidates(self):
        """Stoplist tokens cannot become dominant signals or form clusters."""
        for i in range(5):
            sid = f"sess-{i}"
            self._insert_session(sid, "page")
            self._insert_message(
                sid, "assistant", self._make_terminal_call("cd /tmp"), i * 86400.0 * 8
            )
            self._insert_message(
                sid, "assistant", self._make_terminal_call("ls -la"), i * 86400.0 * 8 + 1
            )
        result = li.mine_lane_ideation(self.domain_map, self.db_path, Path("/nonexistent"))
        self.assertEqual(result["candidate_count"], 0)
        for c in result.get("candidates", []):
            for sig in c["dominant_signals"]:
                self.assertNotIn(sig, {f"bin:{x}" for x in li.SIGNAL_STOPLIST})

    def test_idf_downweights_ubiquitous_signals(self):
        """A signal present in more than half of sessions is excluded from dominance."""
        for i in range(6):
            sid = f"sess-{i}"
            self._insert_session(sid, "page")
            self._insert_message(
                sid, "assistant", self._make_terminal_call("docker ps"), i * 86400.0 * 8
            )
        # Add noise so docker is in 6/11 = 55% > 0.5 (ubiquitous)
        for i in range(5):
            sid = f"noise-{i}"
            self._insert_session(sid, "page")
            self._insert_message(
                sid, "assistant", self._make_terminal_call(f"curl {i}"), i * 3600.0
            )
        result = li.mine_lane_ideation(self.domain_map, self.db_path, Path("/nonexistent"))
        # docker is ubiquitous, so no cluster should form around it
        self.assertEqual(result["candidate_count"], 0)

    def test_distinctive_cluster_still_detected(self):
        """A signal that is enriched in a cluster but not ubiquitous is still detected."""
        for i in range(3):
            sid = f"w0-{i}"
            self._insert_session(sid, "page")
            self._insert_message(
                sid, "assistant", self._make_terminal_call("docker ps"), i * 3600.0
            )
        for i in range(2):
            sid = f"w1-{i}"
            self._insert_session(sid, "page")
            self._insert_message(
                sid, "assistant", self._make_terminal_call("docker ps"), 86400.0 * 8 + i * 3600.0
            )
        # Noise sessions: 8 sessions with other commands
        for i in range(8):
            sid = f"noise-{i}"
            self._insert_session(sid, "page")
            self._insert_message(
                sid, "assistant", self._make_terminal_call(f"curl {i}"), i * 3600.0
            )
        result = li.mine_lane_ideation(self.domain_map, self.db_path, Path("/nonexistent"))
        self.assertEqual(result["candidate_count"], 1)
        c = result["candidates"][0]
        self.assertEqual(c["session_count"], 5)
        self.assertIn("bin:docker", c["dominant_signals"])


if __name__ == "__main__":
    unittest.main()
