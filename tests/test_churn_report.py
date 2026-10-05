import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "clear-reflect" / "scripts"
COMMAND = SCRIPTS / "churn-report"


class ChurnReportTest(unittest.TestCase):
    def run_stub(self, stdout, stderr="", status=0, args=()):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            command = root / "churn-report"
            shutil.copyfile(COMMAND, command)
            (root / "mine").write_text(
                "import sys\n"
                "assert sys.argv[1:] == ['--format', 'summary'], sys.argv\n"
                f"sys.stdout.write({stdout!r})\n"
                f"sys.stderr.write({stderr!r})\n"
                f"sys.exit({status})\n"
            )
            return subprocess.run(
                [sys.executable, str(command), *args],
                capture_output=True,
                env={**os.environ, "HOME": td},
                cwd=td,
            )

    def test_extracts_only_churn_section_and_preserves_success_stderr(self):
        section = (
            "Context churn: 4 kanban runs, 2 cards\n"
            "  restart churn: 1 cards with 3+ runs hold 98.8% of card tokens\n"
            "    t_aaa: 3 runs, 9,450,000 tok\n"
            "  resend amplification: median 3150.0x input-to-output\n"
            "  kanban_show refetch: 3 calls\n"
            "  proposal: triage repeated restarts\n"
        )
        result = self.run_stub(
            "Oversized results: 1 finding(s)\n\nLane ideation: no candidates\n\n"
            + section,
            "miner diagnostic\n",
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, section.encode())
        self.assertEqual(result.stderr, b"miner diagnostic\n")

    def test_stops_at_next_top_level_section(self):
        result = self.run_stub(
            "Context churn: 1 kanban runs, 1 cards\n"
            "  proposal: cap worker context\n\n"
            "Another detector: finding\n  unrelated detail\n"
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout,
            b"Context churn: 1 kanban runs, 1 cards\n"
            b"  proposal: cap worker context\n\n",
        )
        self.assertEqual(result.stderr, b"")

    def test_preserves_note_without_trailing_newline(self):
        result = self.run_stub("Other detector: note\nContext churn: no readable state dbs found")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"Context churn: no readable state dbs found")
        self.assertEqual(result.stderr, b"")

    def test_miner_failure_preserves_exit_and_stderr_without_partial_report(self):
        for stdout in ("", "Context churn: partial report\n"):
            with self.subTest(stdout=stdout):
                result = self.run_stub(stdout, "miner failed\ntrace detail", 23)
                self.assertEqual(result.returncode, 23)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr, b"miner failed\ntrace detail")

    def test_missing_section_fails_instead_of_reporting_success(self):
        result = self.run_stub("Other detector: note\n", "miner diagnostic\n")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(
            result.stderr,
            b"miner diagnostic\nchurn-report: mine summary has no Context churn section\n",
        )

    def test_help_does_not_run_miner(self):
        result = self.run_stub("", "miner must not run", 23, args=("--help",))
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"usage: churn-report", result.stdout)
        self.assertEqual(result.stderr, b"")

    def test_real_miner_uses_only_isolated_home(self):
        with tempfile.TemporaryDirectory() as td:
            # A temporary HOME isolates default state.db, profiles, skills, and boards.
            result = subprocess.run(
                [sys.executable, str(COMMAND)],
                capture_output=True,
                env={**os.environ, "HOME": td},
                cwd=td,
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"Context churn: no readable state dbs found\n")
        self.assertEqual(result.stderr, b"")


if __name__ == "__main__":
    unittest.main()
