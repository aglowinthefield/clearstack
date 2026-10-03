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
                responder=lambda r, p, s, f: {},
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
                responder=lambda r, p, s, f: {"response": "fake"},
            )
        self.assertEqual(code, 0)
        self.assertEqual(len(emitted), 2)
        self.assertEqual(json.loads(emitted[0])["job_name"], "build")
        self.assertEqual(json.loads(emitted[1])["response"], "fake")

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


class ClassifyTest(unittest.TestCase):
    def test_changed_file_path_in_log_is_pr_caused(self):
        verdict, evidence = watch_module.classify(
            "FAIL src/app.py\nTypeError: boom", ["src/app.py", "README.md"])
        self.assertEqual(verdict, "pr-caused")
        self.assertEqual(evidence, ["src/app.py"])

    def test_changed_file_basename_in_log_is_pr_caused(self):
        verdict, evidence = watch_module.classify(
            "Error in app.py: something broke", ["src/deep/app.py"])
        self.assertEqual(verdict, "pr-caused")
        self.assertEqual(evidence, ["src/deep/app.py"])

    def test_infra_signature_is_infra(self):
        verdict, evidence = watch_module.classify(
            "##[error]The operation was canceled.", ["src/app.py"])
        self.assertEqual(verdict, "infra")
        self.assertEqual(evidence, ["the operation was canceled"])

    def test_infra_signature_wins_over_a_path_match(self):
        verdict, _ = watch_module.classify(
            "src/app.py\nThe runner has received a shutdown signal", ["src/app.py"])
        self.assertEqual(verdict, "infra")

    def test_no_path_match_is_unknown(self):
        verdict, evidence = watch_module.classify(
            "FAIL test/other_test.py\nAssertionError", ["src/app.py"])
        self.assertEqual(verdict, "unknown")
        self.assertEqual(evidence, ["no changed-file path appears in the failed-log tail"])

    def test_unreadable_log_is_unknown(self):
        verdict, evidence = watch_module.classify(None, ["src/app.py"])
        self.assertEqual(verdict, "unknown")
        self.assertEqual(evidence, ["failed-log tail unreadable"])

    def test_unreadable_changed_files_is_unknown(self):
        verdict, _ = watch_module.classify("FAIL test/foo.py", None)
        self.assertEqual(verdict, "unknown")


class RespondTest(unittest.TestCase):
    def _respond(self, log_tail, files):
        import unittest.mock as mock
        failure = {"run_id": 10, "job_id": 20, "job_name": "test",
                   "workflow": "CI", "html_url": "u"}
        with mock.patch.object(watch_module, "failed_log_tail", lambda r, run, j: log_tail), \
             mock.patch.object(watch_module, "changed_files", lambda r, p: files), \
             mock.patch.object(watch_module, "branch_name", lambda r, p: "fix-branch"):
            return watch_module.respond("OWNER/REPO", 3, "abc123", failure)

    def test_pr_caused_dispatches_a_repair_with_the_full_brief(self):
        record = self._respond("FAIL src/app.py", ["src/app.py"])
        self.assertEqual(record["response"], "dispatch_repair")
        self.assertEqual(record["classification"], "pr-caused")
        self.assertEqual(record["evidence"], ["src/app.py"])
        self.assertEqual(record["run_id"], 10)
        self.assertEqual(record["job_id"], 20)
        self.assertEqual(record["job_name"], "test")
        self.assertEqual(record["pr_url"], "https://github.com/OWNER/REPO/pull/3")
        self.assertEqual(record["head_sha"], "abc123")
        self.assertEqual(record["branch"], "fix-branch")
        self.assertEqual(record["changed_files"], ["src/app.py"])
        self.assertEqual(record["log_tail"], "FAIL src/app.py")
        self.assertIn("fix-branch", record["instructions"])
        self.assertIn("Never open another pull request", record["instructions"])
        self.assertEqual(record["spawned_by"], "clear-ci")
        self.assertIsNone(record["parent_run_id"])

    def test_unrelated_failure_requests_an_operator_decision(self):
        record = self._respond("The operation was canceled.", ["src/app.py"])
        self.assertEqual(record["response"], "request_operator_decision")
        self.assertEqual(record["classification"], "infra")
        self.assertNotIn("instructions", record)

    def test_unknown_failure_requests_an_operator_decision(self):
        record = self._respond("FAIL test/other.py", ["src/app.py"])
        self.assertEqual(record["response"], "request_operator_decision")
        self.assertEqual(record["classification"], "unknown")


class ControlLoopTest(unittest.TestCase):
    def _run_loop(self, states_per_run, log_tail, files, run_ids=(1,)):
        """Drive watch() with per-run state sequences; return (exit code, parsed lines)."""
        import unittest.mock as mock
        counts = {run_id: 0 for run_id in run_ids}

        def fake_run_detail(repo, run_id):
            states = states_per_run[run_id]
            state = states[min(counts[run_id], len(states) - 1)]
            counts[run_id] += 1
            return state

        emitted = []
        with mock.patch.object(watch_module, "head_sha", lambda r, p: "sha"), \
             mock.patch.object(watch_module, "workflow_run_ids", lambda r, s: list(run_ids)), \
             mock.patch.object(watch_module, "run_detail", fake_run_detail), \
             mock.patch.object(watch_module, "failed_log_tail", lambda r, run, j: log_tail), \
             mock.patch.object(watch_module, "changed_files", lambda r, p: files), \
             mock.patch.object(watch_module, "branch_name", lambda r, p: "fix-branch"):
            code = watch_module.watch(
                "OWNER/REPO", 3, interval=1, max_seconds=10,
                sleep=lambda s: None, clock=lambda: 0,
                emit=lambda *a, **k: emitted.append(a[0]),
            )
        return code, [json.loads(line) for line in emitted]

    def test_real_failure_produces_exactly_one_response(self):
        code, lines = self._run_loop(
            {1: [{"status": "completed", "workflowName": "CI",
                  "jobs": [{"databaseId": 1, "name": "test", "conclusion": "failure", "url": "u"}]}]},
            "FAIL src/app.py", ["src/app.py"])
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["job_name"], "test")
        self.assertEqual(lines[1]["response"], "dispatch_repair")

    def test_skipped_dependency_job_produces_no_response(self):
        code, lines = self._run_loop(
            {1: [{"status": "completed", "workflowName": "CI",
                  "jobs": [{"databaseId": 1, "name": "build", "conclusion": "success", "url": "u1"},
                           {"databaseId": 2, "name": "deploy", "conclusion": "skipped", "url": "u2"}]}]},
            "FAIL src/app.py", ["src/app.py"])
        self.assertEqual(code, 0)
        self.assertEqual(lines, [])

    def test_a_duplicate_poll_produces_no_second_response(self):
        state = {"status": "in_progress", "workflowName": "CI",
                 "jobs": [{"databaseId": 1, "name": "test", "conclusion": "failure", "url": "u"}]}
        done = {"status": "completed", "workflowName": "CI",
                "jobs": [{"databaseId": 1, "name": "test", "conclusion": "failure", "url": "u"}]}
        code, lines = self._run_loop({1: [state, state, done]}, "FAIL src/app.py", ["src/app.py"])
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[1]["response"], "dispatch_repair")

    def test_unrelated_failure_produces_an_operator_decision(self):
        code, lines = self._run_loop(
            {1: [{"status": "completed", "workflowName": "CI",
                  "jobs": [{"databaseId": 1, "name": "test", "conclusion": "failure", "url": "u"}]}]},
            "FAIL test/unrelated.py", ["src/app.py"])
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[1]["response"], "request_operator_decision")

    def test_the_loop_keeps_watching_after_a_handled_failure(self):
        run_one = [
            {"status": "in_progress", "workflowName": "CI",
             "jobs": [{"databaseId": 1, "name": "test", "conclusion": "failure", "url": "u1"}]},
            {"status": "completed", "workflowName": "CI",
             "jobs": [{"databaseId": 1, "name": "test", "conclusion": "failure", "url": "u1"}]},
        ]
        run_two = [
            {"status": "in_progress", "workflowName": "Lint",
             "jobs": [{"databaseId": 2, "name": "lint", "conclusion": None, "url": "u2"}]},
            {"status": "completed", "workflowName": "Lint",
             "jobs": [{"databaseId": 2, "name": "lint", "conclusion": "failure", "url": "u2"}]},
        ]
        code, lines = self._run_loop({1: run_one, 2: run_two}, "FAIL src/app.py",
                                     ["src/app.py"], run_ids=(1, 2))
        self.assertEqual(code, 0)
        responses = [line for line in lines if "response" in line]
        failures = [line for line in lines if "response" not in line]
        self.assertEqual(len(failures), 2)
        self.assertEqual(len(responses), 2)
        self.assertEqual({f["job_name"] for f in failures}, {"test", "lint"})
        self.assertTrue(all(r["response"] == "dispatch_repair" for r in responses))


if __name__ == "__main__":
    unittest.main()
