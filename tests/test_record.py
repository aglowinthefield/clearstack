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

    def test_focus_updates_are_logged_as_distinct_events(self):
        run_id = self.run_record("start", "--task", "migrate billing").stdout.strip()
        self.run_record("focus", run_id, "waiting on which rollout strategy to use")
        self.run_record("focus", run_id, "rollout decided, now wiring the flag")
        self.run_record("end", run_id, "--status", "done")

        log = self.log()
        focus_events = [e for e in log if e["event"] == "focus"]
        self.assertEqual(len(focus_events), 2)
        self.assertEqual(focus_events[0]["text"], "waiting on which rollout strategy to use")
        self.assertEqual(focus_events[-1]["text"], "rollout decided, now wiring the flag")

    def test_focus_on_unknown_run_is_refused(self):
        result = self.run_record("focus", "cr-19700101-000000", "some update")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no run", result.stderr)

    def test_parked_run_must_name_the_decision_it_needs(self):
        run_id = self.run_record("start", "--task", "migrate store").stdout.strip()
        result = self.run_record("end", run_id, "--status", "parked")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([e["event"] for e in self.log()], ["start"])

    def test_start_with_parent_run_records_the_link(self):
        parent_id = self.run_record("start", "--task", "parent task").stdout.strip()
        child_id = self.run_record("start", "--task", "child task",
                                    "--parent-run", parent_id, "--spawned-by", "delegate_task").stdout.strip()
        log = self.log()
        child_start = next(e for e in log if e["run"] == child_id and e["event"] == "start")
        self.assertEqual(child_start["parent_run_id"], parent_id)
        self.assertEqual(child_start["spawned_by"], "delegate_task")

    def test_start_without_parent_run_has_no_lineage_fields(self):
        run_id = self.run_record("start", "--task", "standalone").stdout.strip()
        start = next(e for e in self.log() if e["run"] == run_id)
        self.assertIsNone(start["parent_run_id"])
        self.assertIsNone(start["spawned_by"])

    def test_parent_run_env_var_is_used_when_flag_omitted(self):
        self.env["CLEARSTACK_PARENT_RUN"] = "cr-from-env"
        run_id = self.run_record("start", "--task", "env-linked child").stdout.strip()
        start = next(e for e in self.log() if e["run"] == run_id)
        self.assertEqual(start["parent_run_id"], "cr-from-env")

    def test_end_without_a_harness_session_id_has_no_telemetry(self):
        env = {k: v for k, v in self.env.items()
               if k not in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "HERMES_SESSION_ID")}
        self.env = env
        run_id = self.run_record("start", "--task", "small fix").stdout.strip()
        self.run_record("end", run_id, "--status", "done")
        end = next(e for e in self.log() if e["event"] == "end")
        self.assertIsNone(end["telemetry"])

    def test_resume_prints_compact_brief(self):
        run_id = self.run_record("start", "--task", "migrate billing", "--playbook", "feature").stdout.strip()
        self.run_record("note", run_id, "decided on approach A")
        self.run_record("focus", run_id, "waiting on API review")
        self.run_record("end", run_id, "--status", "parked", "--needs", "API approval",
                        "--verified", "schema agreed: ADR-004 signed",
                        "--unverified", "migration script not tested")

        result = self.run_record("resume", run_id)
        self.assertEqual(result.returncode, 0)
        out = result.stdout
        self.assertIn("Run: " + run_id, out)
        self.assertIn("Task: migrate billing", out)
        self.assertIn("Playbook: feature", out)
        self.assertIn("Focus: waiting on API review", out)
        self.assertIn("decided on approach A", out)
        self.assertIn("schema agreed: ADR-004 signed", out)
        self.assertIn("migration script not tested", out)
        self.assertIn("Status: parked", out)
        self.assertIn("Needs: API approval", out)
        self.assertLess(len(out), 2048)

    def test_resume_for_running_run_shows_running_status(self):
        run_id = self.run_record("start", "--task", "fix scroll").stdout.strip()
        self.run_record("note", run_id, "hook works, callers untouched")
        result = self.run_record("resume", run_id)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Status: running", result.stdout)
        self.assertIn("hook works, callers untouched", result.stdout)

    def test_resume_for_unknown_run_exits_nonzero(self):
        result = self.run_record("resume", "cr-19700101-000000")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no run", result.stderr)

    def test_resume_truncates_when_over_limit(self):
        run_id = self.run_record("start", "--task", "x").stdout.strip()
        for i in range(30):
            self.run_record("note", run_id, f"note {i}: " + "y" * 80)
        self.run_record("end", run_id, "--status", "done")
        result = self.run_record("resume", run_id, "--limit", "500")
        self.assertEqual(result.returncode, 0)
        self.assertIn("... (truncated)", result.stdout)
        self.assertLessEqual(len(result.stdout), 520)

    def test_confirm_writes_event_with_status_and_reason(self):
        parent_id = self.run_record("start", "--task", "parent").stdout.strip()
        child_id = self.run_record("start", "--task", "child", "--parent-run", parent_id).stdout.strip()
        self.run_record("confirm", parent_id, child_id, "--status", "accepted", "--reason", "tests passed")

        log = self.log()
        confirm = next(e for e in log if e["event"] == "confirm")
        self.assertEqual(confirm["run"], parent_id)
        self.assertEqual(confirm["child_run"], child_id)
        self.assertEqual(confirm["status"], "accepted")
        self.assertEqual(confirm["reason"], "tests passed")

    def test_confirm_requires_existing_parent_run(self):
        child_id = self.run_record("start", "--task", "child").stdout.strip()
        result = self.run_record("confirm", "cr-19700101-000000", child_id, "--status", "accepted")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no run", result.stderr)

    def test_confirm_requires_existing_child_run(self):
        parent_id = self.run_record("start", "--task", "parent").stdout.strip()
        result = self.run_record("confirm", parent_id, "cr-19700101-000000", "--status", "accepted")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no run", result.stderr)

    def test_two_sequential_runs_in_one_session_each_get_their_own_delta(self):
        import sqlite3
        db_path = Path(self.state.name) / "state.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""CREATE TABLE sessions (
            id TEXT PRIMARY KEY, model TEXT, tool_call_count INTEGER,
            input_tokens INTEGER, output_tokens INTEGER,
            cache_read_tokens INTEGER, cache_write_tokens INTEGER,
            estimated_cost_usd REAL, actual_cost_usd REAL)""")
        conn.execute("CREATE TABLE messages (session_id TEXT, tool_name TEXT)")
        conn.execute("INSERT INTO sessions VALUES ('sess-1','claude-sonnet-5',0,0,0,0,0,0,0)")
        conn.commit()

        def set_cumulative(tool_calls, cost, tool_names):
            conn.execute("UPDATE sessions SET tool_call_count=?, estimated_cost_usd=?, actual_cost_usd=? WHERE id='sess-1'",
                         (tool_calls, cost, cost))
            conn.execute("DELETE FROM messages WHERE session_id='sess-1'")
            conn.executemany("INSERT INTO messages VALUES ('sess-1', ?)", [(n,) for n in tool_names])
            conn.commit()

        self.env["HERMES_SESSION_ID"] = "sess-1"
        self.env["HERMES_HOME"] = self.state.name
        env_no_other = {k: v for k, v in self.env.items()
                        if k not in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")}
        self.env = env_no_other

        set_cumulative(0, 0.0, [])
        run_a = self.run_record("start", "--task", "first run").stdout.strip()
        set_cumulative(5, 1.0, ["terminal"] * 5)
        self.run_record("end", run_a, "--status", "done")

        run_b = self.run_record("start", "--task", "second run").stdout.strip()
        set_cumulative(9, 1.5, ["terminal"] * 7 + ["patch"] * 2)
        self.run_record("end", run_b, "--status", "done")
        conn.close()

        log = self.log()
        end_a = next(e for e in log if e["run"] == run_a and e["event"] == "end")
        end_b = next(e for e in log if e["run"] == run_b and e["event"] == "end")

        self.assertEqual(end_a["telemetry"]["tool_calls"], 5)
        self.assertEqual(end_a["telemetry"]["cost_usd"], 1.0)
        self.assertEqual(end_b["telemetry"]["tool_calls"], 4)
        self.assertEqual(end_b["telemetry"]["cost_usd"], 0.5)
        self.assertEqual(end_b["telemetry"]["tool_breakdown"], {"terminal": 2, "patch": 2})


class TelemetryTest(unittest.TestCase):
    def test_claude_code_reads_cost_state_and_tool_use_count(self):
        with tempfile.TemporaryDirectory() as home:
            session_id = "sess-123"
            project_dir = Path(home) / ".claude" / "projects" / "-some-project"
            project_dir.mkdir(parents=True)
            transcript = project_dir / f"{session_id}.jsonl"
            transcript.write_text("\n".join(json.dumps(e) for e in [
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
                {"type": "cost-state", "totalCostUSD": 1.5,
                 "modelUsage": {"m": {"inputTokens": 10, "outputTokens": 5,
                                       "cacheReadInputTokens": 2, "cacheCreationInputTokens": 1}}},
            ]) + "\n")
            with patch.object(record_module.Path, "home", return_value=Path(home)):
                result = record_module._claude_code_telemetry(session_id)
            self.assertEqual(result["source"], "claude-code")
            self.assertEqual(result["cost_usd"], 1.5)
            self.assertEqual(result["tool_calls"], 3)
            self.assertEqual(result["tokens"], {"input": 10, "output": 5, "cache_read": 2, "cache_write": 1})
            self.assertEqual(result["tool_breakdown"], {"Bash": 2, "Read": 1})

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
                "estimated_cost": 0.02, "tool_calls": [{"name": "search_files"}, {"name": "search_files"}, {"name": "terminal"}],
            }))
            with patch.object(record_module.Path, "home", return_value=Path(home)):
                result = record_module._hermes_telemetry(session_id)
            self.assertEqual(result["source"], "hermes")
            self.assertEqual(result["tool_calls"], 3)
            self.assertEqual(result["cost_usd"], 0.02)
            self.assertEqual(result["tool_breakdown"], {"search_files": 2, "terminal": 1})

    def test_hermes_missing_session_file_returns_none(self):
        with tempfile.TemporaryDirectory() as home:
            with patch.object(record_module.Path, "home", return_value=Path(home)):
                self.assertIsNone(record_module._hermes_telemetry("missing"))

    def test_hermes_reads_state_db_model_tokens_and_tool_breakdown(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as home:
            db_path = Path(home) / "state.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("""CREATE TABLE sessions (
                id TEXT PRIMARY KEY, model TEXT, tool_call_count INTEGER,
                input_tokens INTEGER, output_tokens INTEGER,
                cache_read_tokens INTEGER, cache_write_tokens INTEGER,
                estimated_cost_usd REAL, actual_cost_usd REAL)""")
            conn.execute("""CREATE TABLE messages (
                session_id TEXT, tool_name TEXT)""")
            conn.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)",
                         ("sess-1", "claude-sonnet-5", 3, 100, 20, 5, 3, 0.10, 0.12))
            conn.executemany("INSERT INTO messages VALUES (?,?)", [
                ("sess-1", "terminal"), ("sess-1", "terminal"), ("sess-1", "read_file"),
            ])
            conn.commit()
            conn.close()
            with patch.dict(os.environ, {"HERMES_HOME": home}):
                result = record_module._hermes_telemetry("sess-1")
            self.assertEqual(result["source"], "hermes")
            self.assertEqual(result["model"], "claude-sonnet-5")
            self.assertEqual(result["cost_usd"], 0.12)
            self.assertEqual(result["tool_calls"], 3)
            self.assertEqual(result["tool_breakdown"], {"terminal": 2, "read_file": 1})

    def test_hermes_state_db_without_matching_session_falls_back_to_none(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as home:
            db_path = Path(home) / "state.db"
            conn = sqlite3.connect(str(db_path))
            conn.execute("""CREATE TABLE sessions (
                id TEXT PRIMARY KEY, model TEXT, tool_call_count INTEGER,
                input_tokens INTEGER, output_tokens INTEGER,
                cache_read_tokens INTEGER, cache_write_tokens INTEGER,
                estimated_cost_usd REAL, actual_cost_usd REAL)""")
            conn.execute("CREATE TABLE messages (session_id TEXT, tool_name TEXT)")
            conn.commit()
            conn.close()
            with patch.dict(os.environ, {"HERMES_HOME": home}), \
                 patch.object(record_module.Path, "home", return_value=Path(home)):
                self.assertIsNone(record_module._hermes_telemetry("no-such-session"))

    def test_codex_reads_token_count_and_function_call_breakdown(self):
        with tempfile.TemporaryDirectory() as home:
            thread_id = "01a095fe-abc"
            sessions = Path(home) / ".codex" / "sessions" / "2026" / "09" / "12"
            sessions.mkdir(parents=True)
            rollout = sessions / f"rollout-2026-09-12T10-21-08-{thread_id}.jsonl"
            rollout.write_text("\n".join(json.dumps(e) for e in [
                {"type": "event_msg", "payload": {"type": "token_count",
                 "info": {"total_token_usage": {"input_tokens": 50, "output_tokens": 10,
                                                  "cached_input_tokens": 5, "cache_write_input_tokens": 2}}}},
                {"type": "response_item", "payload": {"type": "function_call", "name": "shell"}},
                {"type": "response_item", "payload": {"type": "function_call", "name": "shell"}},
                {"type": "response_item", "payload": {"type": "function_call", "name": "apply_patch"}},
            ]) + "\n")
            with patch.object(record_module.Path, "home", return_value=Path(home)):
                result = record_module._codex_telemetry(thread_id)
            self.assertEqual(result["source"], "codex")
            self.assertEqual(result["tool_calls"], 3)
            self.assertEqual(result["tool_breakdown"], {"shell": 2, "apply_patch": 1})

    def test_codex_missing_rollout_returns_none(self):
        with tempfile.TemporaryDirectory() as home:
            with patch.object(record_module.Path, "home", return_value=Path(home)):
                self.assertIsNone(record_module._codex_telemetry("no-such-thread"))

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

    def test_delta_subtracts_baseline_from_cumulative_totals(self):
        baseline = {"source": "hermes", "model": "claude-sonnet-5",
                    "tokens": {"input": 100, "output": 50, "cache_read": 10, "cache_write": 5},
                    "cost_usd": 1.0, "tool_calls": 5, "tool_breakdown": {"terminal": 3, "patch": 2}}
        current = {"source": "hermes", "model": "claude-sonnet-5",
                   "tokens": {"input": 150, "output": 80, "cache_read": 10, "cache_write": 5},
                   "cost_usd": 1.5, "tool_calls": 9, "tool_breakdown": {"terminal": 5, "patch": 2, "read_file": 2}}

        result = record_module.delta_telemetry(baseline, current)

        self.assertEqual(result["tokens"], {"input": 50, "output": 30, "cache_read": 0, "cache_write": 0})
        self.assertEqual(result["cost_usd"], 0.5)
        self.assertEqual(result["tool_calls"], 4)
        self.assertEqual(result["tool_breakdown"], {"terminal": 2, "read_file": 2})

    def test_delta_without_baseline_returns_current_unchanged(self):
        current = {"source": "hermes", "tokens": {"input": 10}, "cost_usd": 0.1, "tool_calls": 1}
        self.assertEqual(record_module.delta_telemetry(None, current), current)

    def test_delta_with_mismatched_source_returns_current_unchanged(self):
        baseline = {"source": "codex", "tokens": {}, "cost_usd": None, "tool_calls": 0}
        current = {"source": "hermes", "tokens": {"input": 10}, "cost_usd": 0.1, "tool_calls": 1}
        self.assertEqual(record_module.delta_telemetry(baseline, current), current)

    def test_delta_with_no_current_returns_none(self):
        self.assertIsNone(record_module.delta_telemetry({"source": "hermes"}, None))

    def test_delta_clamps_negative_deltas_to_zero(self):
        baseline = {"source": "hermes", "tokens": {"input": 100}, "cost_usd": 2.0, "tool_calls": 10}
        current = {"source": "hermes", "tokens": {"input": 50}, "cost_usd": 1.0, "tool_calls": 3}
        result = record_module.delta_telemetry(baseline, current)
        self.assertEqual(result["tokens"]["input"], 0)
        self.assertEqual(result["cost_usd"], 0.0)
        self.assertEqual(result["tool_calls"], 0)


if __name__ == "__main__":
    unittest.main()
