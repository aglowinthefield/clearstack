import importlib.util
import json
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock

SHIP = Path(__file__).resolve().parent.parent / "skills" / "ship" / "scripts" / "ship"

_loader = SourceFileLoader("ship_module", str(SHIP))
_spec = importlib.util.spec_from_loader("ship_module", _loader)
ship_module = importlib.util.module_from_spec(_spec)
_loader.exec_module(ship_module)


class PrBriefTest(unittest.TestCase):
    def test_returns_brief_when_pr_is_readable(self):
        with mock.patch.object(ship_module, "run_gh_json", side_effect=[
            {"url": "https://github.com/o/r/pull/1", "headRefOid": "abc123",
             "headRefName": "fix-thing", "state": "OPEN", "title": "Fix thing"},
            "src/app.py\nREADME.md\n",
        ]):
            brief = ship_module.pr_brief("o/r", 1)
        self.assertEqual(brief["pr_url"], "https://github.com/o/r/pull/1")
        self.assertEqual(brief["head_sha"], "abc123")
        self.assertEqual(brief["branch"], "fix-thing")
        self.assertEqual(brief["state"], "OPEN")
        self.assertEqual(brief["changed_files"], ["src/app.py", "README.md"])

    def test_returns_none_when_gh_fails(self):
        with mock.patch.object(ship_module, "run_gh_json", return_value=None):
            brief = ship_module.pr_brief("o/r", 1)
        self.assertIsNone(brief)

    def test_handles_empty_diff(self):
        with mock.patch.object(ship_module, "run_gh_json", side_effect=[
            {"url": "u", "headRefOid": "sha", "headRefName": "main", "state": "OPEN", "title": "T"},
            "",
        ]):
            brief = ship_module.pr_brief("o/r", 1)
        self.assertEqual(brief["changed_files"], [])


class CheckTest(unittest.TestCase):
    def test_open_pr_is_ready(self):
        with mock.patch.object(ship_module, "run_gh_json", side_effect=[
            {"url": "u", "headRefOid": "sha", "headRefName": "b", "state": "OPEN", "title": "T"},
            "src/app.py\n",
        ]):
            result = ship_module.check("o/r", 1)
        self.assertTrue(result["ready"])
        self.assertEqual(result["state"], "OPEN")

    def test_closed_pr_is_not_ready(self):
        with mock.patch.object(ship_module, "run_gh_json", side_effect=[
            {"url": "u", "headRefOid": "sha", "headRefName": "b", "state": "MERGED", "title": "T"},
            "src/app.py\n",
        ]):
            result = ship_module.check("o/r", 1)
        self.assertFalse(result["ready"])
        self.assertIn("MERGED", result["reason"])

    def test_unreadable_pr_is_not_ready(self):
        with mock.patch.object(ship_module, "run_gh_json", return_value=None):
            result = ship_module.check("o/r", 1)
        self.assertFalse(result["ready"])
        self.assertIn("could not read", result["reason"])


class MilestoneTest(unittest.TestCase):
    def test_milestone_has_tag_and_data(self):
        record = ship_module.milestone("watching", {"pr": 1})
        self.assertEqual(record["milestone"], "watching")
        self.assertEqual(record["data"], {"pr": 1})


class CliTest(unittest.TestCase):
    def test_brief_prints_json(self):
        with mock.patch.object(ship_module, "run_gh_json", side_effect=[
            {"url": "u", "headRefOid": "sha", "headRefName": "b", "state": "OPEN", "title": "T"},
            "src/app.py\n",
        ]):
            import io
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf), mock.patch("sys.argv", ["ship", "brief", "--repo", "o/r", "--pr", "1"]):
                ship_module.main()
            out = json.loads(buf.getvalue())
            self.assertEqual(out["state"], "OPEN")

    def test_check_prints_json(self):
        with mock.patch.object(ship_module, "run_gh_json", side_effect=[
            {"url": "u", "headRefOid": "sha", "headRefName": "b", "state": "OPEN", "title": "T"},
            "src/app.py\n",
        ]):
            import io
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf), mock.patch("sys.argv", ["ship", "check", "--repo", "o/r", "--pr", "1"]):
                ship_module.main()
            out = json.loads(buf.getvalue())
            self.assertTrue(out["ready"])

    def test_milestone_prints_json(self):
        import io
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf), mock.patch("sys.argv", ["ship", "milestone", "--tag", "watching", "--data", '{"pr":1}']):
            ship_module.main()
        out = json.loads(buf.getvalue())
        self.assertEqual(out["milestone"], "watching")
        self.assertEqual(out["data"], {"pr": 1})


if __name__ == "__main__":
    unittest.main()
