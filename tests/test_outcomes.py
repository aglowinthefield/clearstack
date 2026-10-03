import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

OUTCOMES = Path(__file__).resolve().parent.parent / "skills" / "clear-stats" / "scripts" / "outcomes"

_loader = SourceFileLoader("outcomes_module", str(OUTCOMES))
_spec = importlib.util.spec_from_loader("outcomes_module", _loader)
outcomes = importlib.util.module_from_spec(_spec)
_loader.exec_module(outcomes)

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
}


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args],
                   env=GIT_ENV, capture_output=True, check=True)


class RepoFixture:
    """A temporary git repo on branch main plus a runs.jsonl log."""

    def __init__(self, test):
        self.dir = tempfile.TemporaryDirectory()
        test.addCleanup(self.dir.cleanup)
        self.repo = Path(self.dir.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        self.log = Path(self.dir.name) / "runs.jsonl"

    def commit(self, filename, content, message, trailer=None):
        path = self.repo / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        git(self.repo, "add", filename)
        body = message if trailer is None else f"{message}\n\nClear-Run: {trailer}"
        git(self.repo, "commit", "-m", body)
        return git_stdout(self.repo, "rev-parse", "HEAD")

    def write_log(self, events):
        with self.log.open("w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

    def run_events(self, run_id, task="task", status="done", cwd=None, pr=None):
        events = [{"event": "start", "run": run_id, "task": task,
                   "cwd": str(cwd or self.repo)}]
        end = {"event": "end", "run": run_id, "status": status,
               "verified": ["claim: evidence"], "unverified": []}
        if pr:
            end["pr"] = pr
        events.append(end)
        return events


def git_stdout(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          env=GIT_ENV, capture_output=True, text=True,
                          check=True).stdout.strip()


def run_outcome(report, run_id):
    return next(r for r in report["runs"] if r["run"] == run_id)


class OutcomesTest(unittest.TestCase):
    def setUp(self):
        self.fx = RepoFixture(self)

    def collect(self, **kwargs):
        return outcomes.collect(self.fx.log, **kwargs)

    def test_landed_commit_is_verified(self):
        self.fx.commit("a.txt", "one", "add a", trailer="cr-run-1")
        self.fx.write_log(self.fx.run_events("cr-run-1"))

        record = run_outcome(self.collect(), "cr-run-1")
        self.assertEqual(record["outcome"], "landed")
        self.assertEqual(record["confidence"], "verified")
        git_ev = record["evidence"]["git"]
        self.assertTrue(git_ev["available"])
        self.assertEqual(git_ev["default_ref"], "main")
        self.assertEqual(len(git_ev["commits"]), 1)
        self.assertTrue(git_ev["commits"][0]["on_default_branch"])
        self.assertEqual(git_ev["followup_commits"], [])

    def test_later_commit_on_same_paths_marks_reworked(self):
        self.fx.commit("a.txt", "one", "add a", trailer="cr-run-2")
        self.fx.commit("a.txt", "two", "fix a by hand")
        self.fx.commit("b.txt", "unrelated", "add b")
        self.fx.write_log(self.fx.run_events("cr-run-2"))

        record = run_outcome(self.collect(), "cr-run-2")
        self.assertEqual(record["outcome"], "reworked")
        self.assertEqual(len(record["evidence"]["git"]["followup_commits"]), 1)

    def test_reverted_commit_marks_reverted(self):
        sha = self.fx.commit("a.txt", "one", "add a", trailer="cr-run-3")
        git(self.fx.repo, "revert", "--no-edit", sha)
        self.fx.write_log(self.fx.run_events("cr-run-3"))

        record = run_outcome(self.collect(), "cr-run-3")
        self.assertEqual(record["outcome"], "reverted")
        commit = record["evidence"]["git"]["commits"][0]
        self.assertEqual(len(commit["reverted_by"]), 1)

    def test_revert_on_unmerged_branch_does_not_flip_outcome(self):
        sha = self.fx.commit("a.txt", "one", "add a", trailer="cr-run-4")
        git(self.fx.repo, "checkout", "-b", "side")
        git(self.fx.repo, "revert", "--no-edit", sha)
        git(self.fx.repo, "checkout", "main")
        self.fx.write_log(self.fx.run_events("cr-run-4"))

        record = run_outcome(self.collect(), "cr-run-4")
        self.assertEqual(record["outcome"], "landed")

    def test_commit_on_unmerged_branch_is_not_landed(self):
        self.fx.commit("init.txt", "init", "initial commit")
        git(self.fx.repo, "checkout", "-b", "feature")
        self.fx.commit("a.txt", "one", "add a", trailer="cr-run-5")
        git(self.fx.repo, "checkout", "main")
        self.fx.write_log(self.fx.run_events("cr-run-5"))

        record = run_outcome(self.collect(), "cr-run-5")
        self.assertEqual(record["outcome"], "not_landed")
        self.assertEqual(record["confidence"], "verified")
        self.assertFalse(record["evidence"]["git"]["commits"][0]["on_default_branch"])

    def test_partial_landing_is_distinct(self):
        self.fx.commit("a.txt", "one", "add a", trailer="cr-run-6")
        git(self.fx.repo, "checkout", "-b", "feature")
        self.fx.commit("b.txt", "two", "add b", trailer="cr-run-6")
        git(self.fx.repo, "checkout", "main")
        self.fx.write_log(self.fx.run_events("cr-run-6"))

        record = run_outcome(self.collect(), "cr-run-6")
        self.assertEqual(record["outcome"], "partially_landed")

    def test_run_without_commits_is_unverified_not_zero(self):
        self.fx.commit("a.txt", "one", "unrelated")
        self.fx.write_log(self.fx.run_events("cr-run-7"))

        record = run_outcome(self.collect(), "cr-run-7")
        self.assertEqual(record["outcome"], "no_commits")
        self.assertEqual(record["confidence"], "unverified")
        self.assertEqual(record["self_report"]["status"], "done")

    def test_non_git_directory_is_unknown_not_an_error(self):
        plain = Path(self.fx.dir.name) / "plain"
        plain.mkdir()
        self.fx.write_log(self.fx.run_events("cr-run-8", cwd=plain))
        # Stop git from discovering an unrelated enclosing repository.
        with patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": self.fx.dir.name}):
            record = run_outcome(self.collect(), "cr-run-8")
        self.assertEqual(record["outcome"], "unknown")
        git_ev = record["evidence"]["git"]
        self.assertFalse(git_ev["available"])
        self.assertIn("not a git repository", git_ev["note"])

    def test_missing_log_produces_an_empty_report(self):
        report = outcomes.collect(Path(self.fx.dir.name) / "absent.jsonl")
        self.assertEqual(report["runs"], [])
        self.assertIn("not found", report["sources"]["runs_jsonl"]["note"])

    def test_malformed_log_lines_are_skipped_and_counted(self):
        self.fx.commit("a.txt", "one", "add a", trailer="cr-run-9")
        events = self.fx.run_events("cr-run-9")
        with self.fx.log.open("w") as f:
            f.write("not json\n")
            for event in events:
                f.write(json.dumps(event) + "\n")

        report = self.collect()
        self.assertIn("1 unreadable", report["sources"]["runs_jsonl"]["note"])
        self.assertEqual(run_outcome(report, "cr-run-9")["outcome"], "landed")

    def test_parent_rejection_overrides_git_evidence(self):
        self.fx.commit("a.txt", "one", "repair", trailer="cr-child")
        events = self.fx.run_events("cr-parent", task="ship")
        events += self.fx.run_events("cr-child", task="repair CI")
        events[2]["parent_run_id"] = "cr-parent"
        events.append({"event": "confirm", "run": "cr-parent",
                       "child_run": "cr-child", "status": "rejected",
                       "reason": "repair broke the build worse"})
        self.fx.write_log(events)

        report = self.collect()
        child = run_outcome(report, "cr-child")
        self.assertEqual(child["outcome"], "rejected")
        self.assertEqual(child["confidence"], "verified")
        self.assertEqual(child["parent_confirmation"]["status"], "rejected")
        parent = run_outcome(report, "cr-parent")
        self.assertEqual(parent["child_confirmations"][0]["child_run"], "cr-child")

    def test_parent_acceptance_is_recorded_without_overriding(self):
        self.fx.commit("a.txt", "one", "repair", trailer="cr-child")
        events = self.fx.run_events("cr-parent", task="ship")
        events += self.fx.run_events("cr-child", task="repair CI")
        events[2]["parent_run_id"] = "cr-parent"
        events.append({"event": "confirm", "run": "cr-parent",
                       "child_run": "cr-child", "status": "accepted"})
        self.fx.write_log(events)

        child = run_outcome(self.collect(), "cr-child")
        self.assertEqual(child["outcome"], "landed")
        self.assertEqual(child["parent_confirmation"]["status"], "accepted")

    def test_github_is_off_by_default(self):
        self.fx.commit("a.txt", "one", "add a", trailer="cr-run-10")
        self.fx.write_log(self.fx.run_events("cr-run-10"))

        gh_ev = run_outcome(self.collect(), "cr-run-10")["evidence"]["github"]
        self.assertFalse(gh_ev["requested"])
        self.assertFalse(gh_ev["available"])
        self.assertEqual(gh_ev["note"], "not requested")

    def test_github_failure_is_unavailable_evidence_not_a_verdict(self):
        self.fx.commit("a.txt", "one", "add a", trailer="cr-run-11")
        self.fx.write_log(self.fx.run_events("cr-run-11", pr="7"))

        def failing_gh(args):
            return None

        report = outcomes.collect(self.fx.log, github=True, gh=failing_gh)
        record = run_outcome(report, "cr-run-11")
        gh_ev = record["evidence"]["github"]
        self.assertTrue(gh_ev["requested"])
        self.assertFalse(gh_ev["available"])
        self.assertIsNotNone(gh_ev["note"])
        self.assertEqual(record["outcome"], "landed")

    def test_github_merged_pr_rescues_unmerged_local_branch(self):
        self.fx.commit("init.txt", "init", "initial commit")
        git(self.fx.repo, "checkout", "-b", "feature")
        self.fx.commit("a.txt", "one", "add a", trailer="cr-run-12")
        git(self.fx.repo, "checkout", "main")
        git(self.fx.repo, "remote", "add", "origin",
            "https://github.com/owner/repo.git")
        self.fx.write_log(self.fx.run_events(
            "cr-run-12", pr="https://github.com/owner/repo/pull/7"))

        def fake_gh(args):
            if args[0] == "pr" and args[1] == "view":
                return {"number": 7, "url": "https://github.com/owner/repo/pull/7",
                        "state": "MERGED", "mergedAt": "2026-10-01T00:00:00Z",
                        "mergeCommit": {"oid": "abc123"},
                        "reviewDecision": "APPROVED", "headRefOid": "def456",
                        "statusCheckRollup": [
                            {"conclusion": "SUCCESS"}, {"conclusion": "SUCCESS"}]}
            return None

        report = outcomes.collect(self.fx.log, github=True, gh=fake_gh)
        record = run_outcome(report, "cr-run-12")
        self.assertEqual(record["outcome"], "landed")
        gh_ev = record["evidence"]["github"]
        self.assertTrue(gh_ev["available"])
        self.assertEqual(gh_ev["pr"]["state"], "MERGED")
        self.assertEqual(gh_ev["pr"]["checks"], {"SUCCESS": 2})

    def test_github_closed_pr_marks_not_landed(self):
        git(self.fx.repo, "remote", "add", "origin",
            "git@github.com:owner/repo.git")
        self.fx.write_log(self.fx.run_events("cr-run-13", pr="9"))

        def fake_gh(args):
            if args[0] == "pr" and args[1] == "view":
                return {"number": 9, "state": "CLOSED", "mergedAt": None,
                        "mergeCommit": None, "reviewDecision": "CHANGES_REQUESTED",
                        "headRefOid": "def456", "statusCheckRollup": []}
            return None

        report = outcomes.collect(self.fx.log, github=True, gh=fake_gh)
        record = run_outcome(report, "cr-run-13")
        self.assertEqual(record["outcome"], "not_landed")
        self.assertEqual(record["confidence"], "verified")

    def test_run_filter_collects_only_named_runs(self):
        self.fx.commit("a.txt", "one", "add a", trailer="cr-run-14")
        events = self.fx.run_events("cr-run-14") + self.fx.run_events("cr-run-15")
        self.fx.write_log(events)

        report = self.collect(run_filter=["cr-run-14"])
        self.assertEqual([r["run"] for r in report["runs"]], ["cr-run-14"])

    def test_summary_names_claim_vs_proof_gaps(self):
        self.fx.commit("init.txt", "init", "initial commit")
        git(self.fx.repo, "checkout", "-b", "feature")
        self.fx.commit("a.txt", "one", "add a", trailer="cr-run-16")
        git(self.fx.repo, "checkout", "main")
        self.fx.write_log(self.fx.run_events("cr-run-16"))

        report = self.collect()
        self.assertIn("not_landed: 1", report["summary"])
        self.assertIn("cr-run-16", report["summary"])

    def test_cli_emits_json_report(self):
        self.fx.commit("a.txt", "one", "add a", trailer="cr-run-17")
        self.fx.write_log(self.fx.run_events("cr-run-17"))

        result = subprocess.run(
            [str(OUTCOMES), "--runs", str(self.fx.log), "--format", "json"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(run_outcome(report, "cr-run-17")["outcome"], "landed")


if __name__ == "__main__":
    unittest.main()
