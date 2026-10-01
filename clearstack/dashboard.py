"""Read-only local dashboard for ClearStack run records."""

import argparse
from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


def default_log_path():
    state_home = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(state_home) / "clearstack" / "runs.jsonl"


def load_runs(path=None):
    """Read event records and group them into newest-first runs."""
    log_path = Path(path) if path is not None else default_log_path()
    if not log_path.exists():
        return []

    events_by_run = {}
    with log_path.open(encoding="utf-8") as log:
        for line_number, line in enumerate(log, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{log_path}:{line_number}: invalid JSON: {error.msg}") from error
            if not isinstance(event, dict):
                raise ValueError(f"{log_path}:{line_number}: expected a JSON object")
            run_id = event.get("run")
            if not isinstance(run_id, str) or not run_id:
                raise ValueError(f"{log_path}:{line_number}: missing run id")
            events_by_run.setdefault(run_id, []).append(event)

    runs = []
    for run_id, events in events_by_run.items():
        starts = [event for event in events if event.get("event") == "start"]
        ends = [event for event in events if event.get("event") == "end"]
        start = starts[0] if starts else {}
        end = ends[-1] if ends else None
        runs.append({
            "id": run_id,
            "start": start,
            "end": end,
            "events": events,
            "started_at": start.get("ts", ""),
            "status": end.get("status", "open") if end else "open",
        })
    return sorted(runs, key=lambda run: (run["started_at"], run["id"]), reverse=True)


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _display_time(value):
    parsed = _parse_time(value)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if parsed else "—"


def _duration(run):
    started = _parse_time(run["started_at"])
    if not started:
        return "—"
    end_time = _parse_time(run["end"].get("ts")) if run["end"] else datetime.now(timezone.utc)
    if not end_time:
        return "—"
    seconds = max(0, int((end_time - started).total_seconds()))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def _claims(title, claims):
    if not claims:
        return ""
    items = "".join(f"<li>{escape(str(claim))}</li>" for claim in claims)
    return f"<section><h3>{escape(title)}</h3><ul>{items}</ul></section>"


def _format_tokens(n):
    return f"{n:,}" if isinstance(n, (int, float)) else "—"


def _telemetry_section(end):
    telemetry = end.get("telemetry") if end else None
    if not telemetry:
        return "<section><h3>Telemetry</h3><p class=muted>Not collected for this run.</p></section>"
    tokens = telemetry.get("tokens") or {}
    cost = telemetry.get("cost_usd")
    cost_text = f"${cost:.4f}" if isinstance(cost, (int, float)) else "—"
    rows = "".join(f"""<div><dt>{escape(label)}</dt><dd>{_format_tokens(tokens.get(key, 0))}</dd></div>"""
                    for label, key in (("Input", "input"), ("Output", "output"),
                                        ("Cache read", "cache_read"), ("Cache write", "cache_write")))
    return f"""<section><h3>Telemetry · {escape(str(telemetry.get('source') or 'unknown'))}</h3>
      <dl class=metadata>{rows}
        <div><dt>Tool calls</dt><dd>{_format_tokens(telemetry.get('tool_calls'))}</dd></div>
        <div><dt>Cost</dt><dd>{escape(cost_text)}</dd></div>
      </dl></section>"""


def _detail(run):
    start = run["start"]
    end = run["end"] or {}
    notes = [event.get("text", "") for event in run["events"] if event.get("event") == "note"]
    note_html = "".join(f"<li>{escape(str(note))}</li>" for note in notes)
    if not note_html:
        note_html = "<li class=muted>No decision notes recorded.</li>"
    return f"""<section class=detail id=detail>
      <div class=detail-head><div><p class=eyebrow>RUN DETAIL</p><h2>{escape(run['id'])}</h2></div>
      <a class=back href="/">All runs</a></div>
      <p class=task>{escape(str(start.get('task') or 'Untitled run'))}</p>
      <dl class=metadata>
        <div><dt>Agent</dt><dd>{escape(str(start.get('agent') or 'Unknown'))}</dd></div>
        <div><dt>Started</dt><dd>{escape(_display_time(run['started_at']))}</dd></div>
        <div><dt>Duration</dt><dd>{escape(_duration(run))}</dd></div>
        <div><dt>Status</dt><dd>{escape(str(run['status']))}</dd></div>
        <div><dt>Branch</dt><dd>{escape(str(start.get('branch') or '—'))}</dd></div>
        <div><dt>Commit</dt><dd><code>{escape(str(start.get('head') or '—'))}</code></dd></div>
      </dl>
      <section><h3>Decision notes</h3><ul>{note_html}</ul></section>
      {_telemetry_section(end)}
      {_claims('Verified', end.get('verified', []))}
      {_claims('Unverified', end.get('unverified', []))}
      {f"<section><h3>Needs</h3><p>{escape(str(end['needs']))}</p></section>" if end.get('needs') else ''}
      {f"<section><h3>Pull request</h3><p>{escape(str(end['pr']))}</p></section>" if end.get('pr') else ''}
    </section>"""


def _run_cost(run):
    telemetry = (run["end"] or {}).get("telemetry") if run["end"] else None
    if not telemetry:
        return None
    return telemetry.get("cost_usd")


def _format_cost_cell(run):
    telemetry = (run["end"] or {}).get("telemetry") if run["end"] else None
    if not telemetry:
        return "<span class=muted>—</span>"
    cost = telemetry.get("cost_usd")
    cost_text = f"${cost:.2f}" if isinstance(cost, (int, float)) else "—"
    calls = telemetry.get("tool_calls")
    calls_text = f"{calls:,} calls" if isinstance(calls, (int, float)) else ""
    return f"{escape(cost_text)}<small>{escape(calls_text)}</small>" if calls_text else escape(cost_text)


def render_page(runs, selected_id=None, error=None, bind_host="127.0.0.1"):
    """Render one self-contained HTML page. All run data is escaped."""
    counts = {name: sum(run["status"] == name for run in runs) for name in ("open", "done", "parked", "abandoned")}
    selected = next((run for run in runs if run["id"] == selected_id), None)
    has_telemetry = any((run["end"] or {}).get("telemetry") for run in runs if run["end"])
    total_cost = sum(c for c in (_run_cost(run) for run in runs) if isinstance(c, (int, float)))
    rows = []
    for run in runs:
        start = run["start"]
        task = escape(str(start.get("task") or "Untitled run"))
        agent = escape(str(start.get("agent") or "Unknown"))
        run_id = escape(run["id"], quote=True)
        status = escape(str(run["status"]))
        rows.append(f"""<tr>
          <td><a class=run-link href="/?run={run_id}#detail">{task}<small>{run_id}</small></a></td>
          <td>{agent}</td><td>{escape(_display_time(run['started_at']))}</td>
          <td>{escape(_duration(run))}</td><td><span class="status {status}">{status}</span></td>
          <td>{_format_cost_cell(run)}</td>
        </tr>""")
    if rows:
        table = """<div class=table-wrap><table><thead><tr><th>Task</th><th>Agent</th><th>Started</th><th>Duration</th><th>Status</th><th>Cost</th></tr></thead>
        <tbody>""" + "".join(rows) + "</tbody></table></div>"
    else:
        table = "<p class=empty>No runs recorded yet. Start a task with clear-mode to add one.</p>"

    error_html = f"<p class=error>{escape(error)}</p>" if error else ""
    detail_html = _detail(selected) if selected else ""
    missing = f"<p class=empty>Run '{escape(selected_id)}' was not found.</p>" if selected_id and not selected else ""
    return f"""<!doctype html>
<html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>ClearStack runs</title>
<style>
:root{{--paper:#f4f2ed;--ink:#26232a;--muted:#716d73;--line:#d8d3cf;--pink:#c43f72;--pink-soft:#f4e5eb;--green:#315d4a;--amber:#8b5e1a}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:44px 28px 72px}}header{{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;border-bottom:2px solid var(--ink);padding-bottom:20px}}
h1{{font-size:clamp(32px,5vw,52px);line-height:1;margin:0;letter-spacing:-.045em}}.brand{{color:var(--pink);font-size:13px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;margin:0 0 10px}}
.local{{font:12px ui-monospace,monospace;color:var(--muted);border:1px solid var(--line);padding:6px 9px;white-space:nowrap}}
.summary{{display:flex;gap:38px;padding:20px 0;border-bottom:1px solid var(--line);flex-wrap:wrap}}.metric{{display:flex;align-items:baseline;gap:9px}}.metric strong{{font:600 23px ui-monospace,monospace}}.metric span{{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}}
.telemetry{{margin:24px 0 34px;padding:12px 15px;border-left:3px solid var(--pink);background:var(--pink-soft);font-size:13px}}.telemetry strong{{font-weight:650}}
.section-title{{display:flex;justify-content:space-between;align-items:baseline;margin:0 0 10px}}h2{{font-size:20px;margin:0;letter-spacing:-.02em}}.count{{font:12px ui-monospace,monospace;color:var(--muted)}}
table{{width:100%;border-collapse:collapse;text-align:left}}th{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;font-weight:600;padding:10px 12px;border-bottom:1px solid var(--ink)}}td{{padding:13px 12px;border-bottom:1px solid var(--line);vertical-align:top}}th:first-child,td:first-child{{padding-left:0}}th:last-child,td:last-child{{padding-right:0}}tbody tr:hover{{background:#ece9e4}}
.run-link{{color:var(--ink);text-decoration:none;font-weight:600}}.run-link:hover{{color:var(--pink)}}small{{display:block;font:11px ui-monospace,monospace;color:var(--muted);font-weight:400;margin-top:2px}}
td:nth-child(2),td:nth-child(3),td:nth-child(4){{font-size:13px;color:var(--muted)}}.status{{font-size:12px;text-transform:capitalize}}.status.done{{color:var(--green)}}.status.parked{{color:var(--amber)}}.status.open{{color:var(--pink)}}
.detail{{margin-top:44px;padding-top:22px;border-top:2px solid var(--ink)}}.detail-head{{display:flex;justify-content:space-between;align-items:flex-end}}.eyebrow{{font-size:10px;letter-spacing:.12em;color:var(--pink);font-weight:700;margin:0 0 6px}}.back{{font-size:13px;color:var(--pink)}}.task{{font-size:18px;margin:14px 0}}
.metadata{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px 20px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:15px 0;margin:16px 0 24px}}dt{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}}dd{{margin:2px 0 0;overflow-wrap:anywhere}}code{{font:12px ui-monospace,monospace}}.detail section{{margin:20px 0}}.detail h3{{font-size:14px;margin:0 0 6px}}ul{{padding-left:20px;margin:5px 0}}li{{margin:4px 0;overflow-wrap:anywhere}}.muted,.empty{{color:var(--muted)}}.empty{{padding:25px 0}}.error{{color:#8c243d;background:#f9e5e8;padding:12px}}
@media(max-width:700px){{main{{padding:25px 16px 48px}}header{{align-items:flex-start;flex-direction:column}}.table-wrap{{overflow-x:auto}}table{{min-width:660px}}.summary{{gap:18px}}}}
</style></head><body><main>
<header><div><p class=brand>ClearStack / local run log</p><h1>Runs</h1></div><span class=local>{escape(bind_host)}</span></header>
<div class=summary><div class=metric><strong>{len(runs)}</strong><span>runs</span></div>
<div class=metric><strong>{counts['open']}</strong><span>open</span></div><div class=metric><strong>{counts['done']}</strong><span>done</span></div>
<div class=metric><strong>{counts['parked']}</strong><span>parked</span></div>
{f'<div class=metric><strong>${total_cost:.2f}</strong><span>total cost</span></div>' if has_telemetry else ''}</div>
{"" if has_telemetry else '<div class=telemetry><strong>Token and tool telemetry is not collected yet.</strong> No run in this log has it. Open a run detail to check once one does. Totals are not shown as zero.</div>'}
{error_html}<section><div class=section-title><h2>Recent runs</h2><span class=count>newest first</span></div>{table}</section>
{detail_html}{missing}</main></body></html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    bind_host = "127.0.0.1"

    def do_GET(self):
        request = urlsplit(self.path)
        if request.path != "/":
            self.send_error(404)
            return
        selected_id = parse_qs(request.query).get("run", [None])[0]
        try:
            runs = load_runs()
            page = render_page(runs, selected_id=selected_id, bind_host=self.bind_host)
            status = 200
        except (OSError, ValueError) as error:
            page = render_page([], error=f"Cannot read run log: {error}", bind_host=self.bind_host)
            status = 500
        body = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Do not log local task text or query values to the terminal.
        return


def main():
    parser = argparse.ArgumentParser(description="Serve the local ClearStack run dashboard")
    parser.add_argument("--port", type=int, default=8765, help="port (default: 8765)")
    parser.add_argument("--host", default="127.0.0.1",
                         help="bind address (default: 127.0.0.1, loopback only). "
                              "The dashboard has no auth: only bind beyond loopback on a network you trust, "
                              "e.g. a Tailscale address.")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    DashboardHandler.bind_host = args.host
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    if args.host != "127.0.0.1":
        print(f"Warning: binding to {args.host} exposes run data (tasks, decisions, file paths) "
              f"to anything that can reach port {server.server_port}. No authentication is enforced.")
    print(f"ClearStack dashboard: http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping dashboard.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
