import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

RECORD = Path(__file__).resolve().parent.parent / "skills" / "clear-mode" / "scripts" / "record"

import importlib.util
from importlib.machinery import SourceFileLoader

_loader = SourceFileLoader("record_module", str(RECORD))
_spec = importlib.util.spec_from_loader("record_module", _loader)
record_module = importlib.util.module_from_spec(_spec)
_loader.exec_module(record_module)


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.TemporaryDirectory()
        self.env = {**os.environ, "XDG_STATE_HOME": self.state.name}

    def tearDown(self):
        self.state.cleanup()

    def run_record(self, *args):
        return subprocess.run([str(RECORD), *args], env=self.env, capture_output=True, text=True)

    def log(self):
        path = Path(self.state.name) / "clearstack" / "runs.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_a_run_writes_start_note_and_end_under_one_id(self):
        run_id = self.run_record("start", "--task", "fix scroll drift", "--playbook", "bug-fix").stdout.strip()
        self.run_record("note", run_id, "fixed in the hook, not the three callers")
        self.run_record("end", run_id, "--status", "done", "--verified", "drift gone: 0px over 60s trace")

        log = self.log()
        self.assertEqual([e["event"] for e in log], ["start", "note", "end"])
        self.assertEqual({e["run"] for e in log}, {run_id})
        self.assertEqual(log[0]["task"], "fix scroll drift")
        self.assertEqual(log[2]["verified"], ["drift gone: 0px over 60s trace"])

    def test_unknown_run_is_refused(self):
        result = self.run_record("end", "cr-19700101-000000", "--status", "done")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no run", result.stderr)

    def test_parked_run_must_name_the_decision_it_needs(self):
        run_id = self.run_record("start", "--task", "migrate store").stdout.strip()
        result = self.run_record("end", run_id, "--status", "parked")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([e["event"] for e in self.log()], ["start"])

    def test_end_without_a_harness_session_id_has_no_telemetry(self):
        env = {k: v for k, v in self.env.items()
               if k not in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "HERMES_SESSION_ID")}
        self.env = env
        run_id = self.run_record("start", "--task", "small fix").stdout.strip()
        self.run_record("end", run_id, "--status", "done")
        end = next(e for e in self.log() if e["event"] == "end")
        self.assertIsNone(end["telemetry"])


class TelemetryTest(unittest.TestCase):
    def test_claude_code_reads_cost_state_and_tool_use_count(self):
        with tempfile.TemporaryDirectory() as home:
            session_id = "sess-123"
            project_dir = Path(home) / ".claude" / "projects" / "-some-project"
            project_dir.mkdir(parents=True)
            transcript = project_dir / f"{session_id}.jsonl"
            transcript.write_text("\n".join(json.dumps(e) for e in [
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
                {"type": "cost-state", "totalCostUSD": 1.5,
                 "modelUsage": {"m": {"inputTokens": 10, "outputTokens": 5,
                                       "cacheReadInputTokens": 2, "cacheCreationInputTokens": 1}}},
            ]) + "\n")
            with patch.object(record_module.Path, "home", return_value=Path(home)):
                result = record_module._claude_code_telemetry(session_id)
            self.assertEqual(result["source"], "claude-code")
            self.assertEqual(result["cost_usd"], 1.5)
            self.assertEqual(result["tool_calls"], 1)
            self.assertEqual(result["tokens"], {"input": 10, "output": 5, "cache_read": 2, "cache_write": 1})

    def test_claude_code_missing_transcript_returns_none(self):
        with tempfile.TemporaryDirectory() as home:
            with patch.object(record_module.Path, "home", return_value=Path(home)):
                self.assertIsNone(record_module._claude_code_telemetry("no-such-session"))

    def test_hermes_reads_session_file_token_and_tool_call_fields(self):
        with tempfile.TemporaryDirectory() as home:
            session_id = "20260101_000000_abcdef"
            sessions = Path(home) / ".hermes" / "webui" / "sessions"
            sessions.mkdir(parents=True)
            (sessions / f"{session_id}.json").write_text(json.dumps({
                "input_tokens": 100, "output_tokens": 20,
                "cache_read_tokens": 5, "cache_write_tokens": 3,
                "estimated_cost": 0.02, "tool_calls": [{}, {}],
            }))
            with patch.object(record_module.Path, "home", return_value=Path(home)):
                result = record_module._hermes_telemetry(session_id)
            self.assertEqual(result["source"], "hermes")
            self.assertEqual(result["tool_calls"], 2)
            self.assertEqual(result["cost_usd"], 0.02)

    def test_hermes_missing_session_file_returns_none(self):
        with tempfile.TemporaryDirectory() as home:
            with patch.object(record_module.Path, "home", return_value=Path(home)):
                self.assertIsNone(record_module._hermes_telemetry("missing"))

    def test_telemetry_prefers_claude_code_session_when_set(self):
        with patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "s1"}, clear=False), \
             patch.object(record_module, "_claude_code_telemetry", return_value={"source": "claude-code"}) as cc, \
             patch.object(record_module, "_codex_telemetry") as codex, \
             patch.object(record_module, "_hermes_telemetry") as hermes:
            result = record_module.telemetry()
        self.assertEqual(result, {"source": "claude-code"})
        cc.assert_called_once_with("s1")
        codex.assert_not_called()
        hermes.assert_not_called()

    def test_telemetry_returns_none_without_any_harness_session_id(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "HERMES_SESSION_ID")}
        with patch.dict(os.environ, env, clear=True):
            self.assertIsNone(record_module.telemetry())


if __name__ == "__main__":
    unittest.main()
