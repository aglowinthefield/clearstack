import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/clear-reflect/scripts"))
import review_outcomes


class ReviewOutcomesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.board = self.root / "boards/demo"
        self.board.mkdir(parents=True)
        self.db = self.root / "state.db"
        with closing(sqlite3.connect(self.db)) as c, c:
            c.executescript("""
                CREATE TABLE sessions (id TEXT PRIMARY KEY, profile_name TEXT,
                    parent_session_id TEXT, started_at REAL, input_tokens INTEGER,
                    output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER);
                CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT,
                    role TEXT, content TEXT);
                CREATE TABLE session_model_usage (session_id TEXT, model TEXT,
                    billing_provider TEXT, task TEXT, api_call_count INTEGER);
            """)
        with closing(sqlite3.connect(self.board / "kanban.db")) as c, c:
            c.executescript("""
                CREATE TABLE task_runs (id INTEGER PRIMARY KEY, task_id TEXT, profile TEXT,
                    started_at INTEGER, ended_at INTEGER);
                CREATE TABLE task_events (id INTEGER PRIMARY KEY, task_id TEXT,
                    run_id INTEGER, kind TEXT, payload TEXT, created_at INTEGER);
            """)

    def tearDown(self):
        self.tmp.cleanup()

    def run_record(self, rid, task, profile, start, end, models=("sol",), parent=None):
        with closing(sqlite3.connect(self.board / "kanban.db")) as c, c:
            c.execute("INSERT INTO task_runs VALUES (?,?,?,?,?)", (rid, task, profile, start, end))
        with closing(sqlite3.connect(self.db)) as c, c:
            sid = str(rid)
            c.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)",
                      (sid, profile, parent, start + 1, 100, 10, 20, 0))
            c.execute("INSERT INTO messages (session_id,role,content) VALUES (?,?,?)",
                      (sid, "user", f"work kanban task {task}"))
            for model in models:
                c.execute("INSERT INTO session_model_usage VALUES (?,?,?,?,?)",
                          (sid, model, "provider", "", 1))

    def event(self, task, kind, at, rid=None, **payload):
        with closing(sqlite3.connect(self.board / "kanban.db")) as c, c:
            c.execute("INSERT INTO task_events (task_id,run_id,kind,payload,created_at) VALUES (?,?,?,?,?)",
                      (task, rid, kind, json.dumps(payload), at))

    def submit(self, task, rid, at):
        self.event(task, "review_requested", at, rid, implementer="scribe", reviewer="jester")

    def approve(self, task, rid, at):
        self.event(task, "review_requested", at, rid, implementer="jester", reviewer="tom")

    def report(self, change_at=None):
        return review_outcomes.mine_reviews([("default", self.db)], self.root / "boards", change_at)

    def test_pending_is_not_a_pass_and_human_return_follows_ai_approval(self):
        self.run_record(1, "t_aa", "scribe", 10, 20)
        self.submit("t_aa", 1, 20)
        self.run_record(2, "t_aa", "jester", 21, 30)
        self.event("t_aa", "changes_requested", 30, 2, reviewer="jester")
        self.run_record(3, "t_aa", "scribe", 31, 40)
        self.submit("t_aa", 3, 40)
        self.run_record(4, "t_aa", "jester", 41, 50)
        self.approve("t_aa", 4, 50)
        self.event("t_aa", "review_reopened", 60)
        self.run_record(5, "t_bb", "scribe", 10, 20)
        self.submit("t_bb", 5, 20)
        row = self.report()["cohorts"][0]
        self.assertEqual((row["cards"], row["first_reviews_resolved"], row["first_passbacks"]), (2, 1, 1))
        self.assertEqual(row["first_passback_pct"], 100)
        self.assertEqual(row["pending_reviews"], 1)
        self.assertEqual(row["avg_review_rounds_per_card"], 1.5)
        self.assertEqual((row["human_reviews_resolved"], row["human_passbacks"]), (1, 1))
        self.assertEqual(row["median_seconds_to_ai_approval"], 40)
        self.assertEqual(row["median_tokens_to_ai_approval"], 520)
        self.assertEqual(sum(r["human_passbacks"] for r in self.report()["model_pairs"]), 1)

    def test_actual_mixed_models_exclude_auxiliary_and_unknown_stays_unknown(self):
        self.run_record(1, "t_aa", "scribe", 10, 20, models=("opus", "sol"))
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("INSERT INTO session_model_usage VALUES ('1','haiku','provider','compression',1)")
        self.submit("t_aa", 1, 20)
        self.run_record(2, "t_aa", "jester", 21, 30, models=())
        self.approve("t_aa", 2, 30)
        row = self.report()["model_pairs"][0]
        self.assertEqual(row["implementer_models"], ["provider:opus", "provider:sol"])
        self.assertEqual(row["reviewer_models"], [])
        self.assertEqual(row["reviewer_attribution"], "unknown")
        self.assertEqual(row["implementer_attribution"], "mixed")

    def test_cohorts_separate_before_after_and_cards_crossing_the_change(self):
        for index, (task, start, approved) in enumerate([
            ("t_aa", 10, 30), ("t_bb", 60, 80), ("t_cc", 40, 70)
        ]):
            rid = index * 2 + 1
            self.run_record(rid, task, "scribe", start, start + 5)
            self.submit(task, rid, start + 5)
            self.run_record(rid + 1, task, "jester", start + 6, approved)
            self.approve(task, rid + 1, approved)
        report = self.report(50)
        self.assertEqual({r["cohort"]: r["cards"] for r in report["cohorts"]},
                         {"before": 1, "after": 1, "crossed_change": 1})

    def test_absent_model_usage_and_unmatched_sessions_do_not_become_zero_cost(self):
        self.run_record(1, "t_aa", "scribe", 10, 20)
        self.submit("t_aa", 1, 20)
        self.run_record(2, "t_aa", "jester", 21, 30)
        self.approve("t_aa", 2, 30)
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("DROP TABLE session_model_usage")
            c.execute("DELETE FROM messages WHERE session_id='2'")
        report = self.report()
        row = report["cohorts"][0]
        self.assertIsNone(row["median_tokens_to_ai_approval"])
        self.assertEqual(row["approvals_with_complete_usage"], 0)
        self.assertEqual(report["model_pairs"][0]["implementer_attribution"], "unknown")

    def test_compression_children_and_duplicate_copies_are_counted_once(self):
        self.run_record(1, "t_aa", "scribe", 10, 20)
        self.submit("t_aa", 1, 20)
        self.run_record(2, "t_aa", "jester", 21, 30)
        self.approve("t_aa", 2, 30)
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("INSERT INTO sessions VALUES ('child','scribe','1',15,20,5,0,0)")
            c.execute("INSERT INTO session_model_usage VALUES ('child','kimi','provider','',1)")
        report = review_outcomes.mine_reviews(
            [("default", self.db), ("scribe", self.db)], self.root / "boards")
        self.assertEqual(report["cohorts"][0]["median_tokens_to_ai_approval"], 285)
        self.assertEqual(report["model_pairs"][0]["implementer_models"],
                         ["provider:kimi", "provider:sol"])

    def test_human_completion_and_direct_changes_request_resolve_handoffs(self):
        for rid, task in [(1, "t_aa"), (3, "t_bb")]:
            self.run_record(rid, task, "scribe", 10, 20)
            self.submit(task, rid, 20)
            self.run_record(rid + 1, task, "jester", 21, 30)
            self.approve(task, rid + 1, 30)
        self.event("t_aa", "completed", 40)
        self.event("t_bb", "changes_requested", 40, reviewer="tom")
        row = self.report()["cohorts"][0]
        self.assertEqual((row["human_passbacks"], row["human_reviews_resolved"]), (1, 2))
        self.assertEqual(row["human_passback_pct"], 50)
        self.assertEqual(row["pending_human_reviews"], 0)

    def test_archived_reviews_are_not_pending_or_passing(self):
        self.run_record(1, "t_aa", "scribe", 10, 20)
        self.submit("t_aa", 1, 20)
        self.event("t_aa", "archived", 30)
        row = self.report()["cohorts"][0]
        self.assertEqual(row["first_reviews_resolved"], 0)
        self.assertEqual(row["unresolved_first_reviews"], 1)
        self.assertEqual(row["pending_reviews"], 0)
        self.assertIsNone(row["first_passback_pct"])


if __name__ == "__main__":
    unittest.main()
