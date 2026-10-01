import subprocess
import unittest
from pathlib import Path

VOICE_CHECK = Path(__file__).resolve().parent.parent / "skills" / "clear-voice" / "scripts" / "voice-check"


def voice_check(text):
    return subprocess.run([str(VOICE_CHECK)], input=text, capture_output=True, text=True)


class VoiceCheckTest(unittest.TestCase):
    def test_plain_text_passes(self):
        result = voice_check("Fixed the scroll drift in useScroll. Tests pass: 12/12.\n")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout, "")

    def test_stock_vocabulary_and_em_dash_are_flagged_with_line_and_rule(self):
        result = voice_check("First line is fine.\nWe leverage a robust cache \u2014 nice.\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("<stdin>:2: rule 5:", result.stdout)
        self.assertIn("<stdin>:2: rule 6:", result.stdout)
        self.assertIn("<stdin>:2: rule 15:", result.stdout)

    def test_code_is_not_prose(self):
        text = "Run `leverage --robust` first.\n```\nenhance()  # crucial\n```\n"
        self.assertEqual(voice_check(text).returncode, 0)

    def test_repo_docs_follow_clear_voice(self):
        repo = VOICE_CHECK.parents[3]
        docs = subprocess.run(["git", "ls-files", "*.md"], cwd=repo, capture_output=True, text=True).stdout.split()
        result = subprocess.run([str(VOICE_CHECK), *docs], cwd=repo, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
