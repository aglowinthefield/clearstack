import importlib.util
import json
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

WATCH = Path(__file__).resolve().parent.parent / "skills" / "clear-ci" / "scripts" / "watch"

_loader = SourceFileLoader("watch_module", str(WATCH))
_spec = importlib.util.spec_from_loader("watch_module", _loader)
watch_module = importlib.util.module_from_spec(_spec)
_loader.exec_module(watch_module)


class NewFailuresTest(unittest.TestCase):
    def test_only_jobs_with_conclusion_failure_are_reported(self):
        jobs = [
            {"databaseId": 1, "name": "build", "conclusion": "success", "url": "u1"},
            {"databaseId": 2, "name": "test", "conclusion": "failure", "url": "u2"},
            {"databaseId": 3, "name": "deploy", "conclusion": "skipped", "url": "u3"},
        ]
        seen = set()
        found = watch_module.new_failures(999, "CI", jobs, seen)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["job_name"], "test")
        self.assertEqual(found[0]["run_id"], 999)
        self.assertEqual(found[0]["workflow"], "CI")

    def test_a_failure_already_seen_is_not_reported_again(self):
        jobs = [{"databaseId": 2, "name": "test", "conclusion": "failure", "url": "u2"}]
        seen = set()
        first = watch_module.new_failures(999, "CI", jobs, seen)
        second = watch_module.new_failures(999, "CI", jobs, seen)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

    def test_same_job_id_in_different_runs_is_reported_once_each(self):
        jobs = [{"databaseId": 2, "name": "test", "conclusion": "failure", "url": "u"}]
        seen = set()
        run_a = watch_module.new_failures(100, "CI", jobs, seen)
        run_b = watch_module.new_failures(200, "CI", jobs, seen)
        self.assertEqual(len(run_a), 1)
        self.assertEqual(len(run_b), 1)


class WatchLoopTest(unittest.TestCase):
    def test_stops_clean_once_all_runs_are_completed(self):
        calls = {"head_sha": 0}

        def fake_head_sha(repo, pr):
            calls["head_sha"] += 1
            return "deadbeef"

        def fake_run_ids(repo, sha):
            return [1]

        def fake_run_detail(repo, run_id):
            return {"status": "completed", "workflowName": "CI", "jobs": []}

        emitted = []
        import unittest.mock as mock
        with mock.patch.object(watch_module, "head_sha", fake_head_sha), \
             mock.patch.object(watch_module, "workflow_run_ids", fake_run_ids), \
             mock.patch.object(watch_module, "run_detail", fake_run_detail):
            code = watch_module.watch(
                "OWNER/REPO", 1, interval=1, max_seconds=10,
                sleep=lambda s: None, clock=lambda: 0,
                emit=lambda *a, **k: emitted.append(a[0]),
            )
        self.assertEqual(code, 0)
        self.assertEqual(calls["head_sha"], 1)

    def test_emits_a_failure_line_then_keeps_watching_to_completion(self):
        import unittest.mock as mock

        states = [
            {"status": "in_progress", "workflowName": "CI",
             "jobs": [{"databaseId": 1, "name": "build", "conclusion": None, "url": "u1"}]},
            {"status": "completed", "workflowName": "CI",
             "jobs": [{"databaseId": 1, "name": "build", "conclusion": "failure", "url": "u1"}]},
        ]
        call_count = {"n": 0}

        def fake_run_detail(repo, run_id):
            state = states[min(call_count["n"], len(states) - 1)]
            call_count["n"] += 1
            return state

        emitted = []
        with mock.patch.object(watch_module, "head_sha", lambda r, p: "sha"), \
             mock.patch.object(watch_module, "workflow_run_ids", lambda r, s: [1]), \
             mock.patch.object(watch_module, "run_detail", fake_run_detail):
            code = watch_module.watch(
                "OWNER/REPO", 1, interval=1, max_seconds=10,
                sleep=lambda s: None, clock=lambda: 0,
                emit=lambda *a, **k: emitted.append(a[0]),
            )
        self.assertEqual(code, 0)
        self.assertEqual(len(emitted), 1)
        self.assertEqual(json.loads(emitted[0])["job_name"], "build")

    def test_gives_up_after_max_seconds_with_no_terminal_run(self):
        import unittest.mock as mock

        clock_value = {"t": 0}

        def fake_clock():
            clock_value["t"] += 5
            return clock_value["t"]

        with mock.patch.object(watch_module, "head_sha", lambda r, p: "sha"), \
             mock.patch.object(watch_module, "workflow_run_ids", lambda r, s: []), \
             mock.patch.object(watch_module, "run_detail", lambda r, i: None):
            code = watch_module.watch(
                "OWNER/REPO", 1, interval=1, max_seconds=10,
                sleep=lambda s: None, clock=fake_clock, emit=lambda *a, **k: None,
            )
        self.assertEqual(code, 1)

    def test_unreadable_head_sha_fails_fast(self):
        import unittest.mock as mock
        with mock.patch.object(watch_module, "head_sha", lambda r, p: None):
            code = watch_module.watch(
                "OWNER/REPO", 1, interval=1, max_seconds=10,
                sleep=lambda s: None, clock=lambda: 0, emit=lambda *a, **k: None,
            )
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
