"""Read-only local dashboard for ClearStack run records."""

import argparse
from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import time
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
    return f"""<section class="detail glass" id=detail>
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
:root{{
  --sky-top:#eaf6ff;--sky-mid:#d3ecfb;--sky-bottom:#bfe3fb;
  --glass:rgba(255,255,255,.58);--glass-strong:rgba(255,255,255,.78);--glass-border:rgba(255,255,255,.9);
  --ink:#143450;--muted:#5c7b93;--line:rgba(20,52,80,.14);
  --aqua:#1c9ad6;--aqua-deep:#0e6fa8;--mint:#2bc98f;--coral:#e8637a;--amber:#c98a1d;
  --shadow:0 1px 1px rgba(14,70,110,.06),0 10px 28px -14px rgba(14,70,110,.35);
}}
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;
  background:
    radial-gradient(1100px 460px at 18% -10%,rgba(255,255,255,.9),rgba(255,255,255,0) 60%),
    linear-gradient(180deg,var(--sky-top),var(--sky-mid) 45%,var(--sky-bottom));
  background-attachment:fixed}}
main{{max-width:1100px;margin:0 auto;padding:44px 28px 72px}}
.glass{{background:var(--glass);backdrop-filter:blur(14px) saturate(160%);-webkit-backdrop-filter:blur(14px) saturate(160%);
  border:1px solid var(--glass-border);border-radius:18px;box-shadow:var(--shadow);position:relative;overflow:hidden}}
.glass::before{{content:"";position:absolute;inset:0 0 auto 0;height:46%;
  background:linear-gradient(180deg,rgba(255,255,255,.85),rgba(255,255,255,0));pointer-events:none}}
header.glass{{display:flex;align-items:center;justify-content:space-between;gap:24px;padding:22px 28px;margin-bottom:26px}}
h1{{font-size:clamp(28px,4.4vw,42px);line-height:1;margin:0;letter-spacing:-.03em;
  background:linear-gradient(180deg,var(--aqua-deep),var(--ink));-webkit-background-clip:text;background-clip:text;color:transparent}}
.brand{{color:var(--aqua-deep);font-size:12px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;margin:0 0 8px}}
.head-right{{display:flex;align-items:center;gap:12px}}
.live{{display:flex;align-items:center;gap:7px;font:12px ui-monospace,monospace;color:var(--muted);
  background:var(--glass-strong);border:1px solid var(--glass-border);border-radius:999px;padding:7px 13px 7px 11px}}
.live-dot{{width:8px;height:8px;border-radius:50%;background:var(--mint);box-shadow:0 0 0 0 rgba(43,201,143,.6);animation:pulse 2s infinite}}
.live.offline .live-dot{{background:var(--coral);animation:none;box-shadow:none}}
@keyframes pulse{{0%{{box-shadow:0 0 0 0 rgba(43,201,143,.55)}}70%{{box-shadow:0 0 0 9px rgba(43,201,143,0)}}100%{{box-shadow:0 0 0 0 rgba(43,201,143,0)}}}}
.local{{font:11px ui-monospace,monospace;color:var(--muted);border:1px solid var(--glass-border);background:var(--glass-strong);
  border-radius:999px;padding:7px 13px;white-space:nowrap}}
.summary.glass{{display:flex;gap:30px;padding:18px 26px;margin-bottom:20px;flex-wrap:wrap}}
.metric{{display:flex;align-items:baseline;gap:9px}}.metric strong{{font:700 22px ui-monospace,monospace;color:var(--aqua-deep)}}
.metric span{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}}
.telemetry.glass{{margin:0 0 20px;padding:14px 20px;border-left:4px solid var(--aqua);font-size:13px}}.telemetry strong{{font-weight:650}}
.section-title{{display:flex;justify-content:space-between;align-items:baseline;margin:0 0 12px}}
h2{{font-size:19px;margin:0;letter-spacing:-.02em;color:var(--ink)}}.count{{font:11px ui-monospace,monospace;color:var(--muted)}}
.panel.glass{{padding:8px 10px 2px}}
table{{width:100%;border-collapse:collapse;text-align:left}}
th{{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;font-weight:700;padding:12px 14px;border-bottom:1px solid var(--line)}}
td{{padding:13px 14px;border-bottom:1px solid var(--line);vertical-align:top}}
tbody tr:hover{{background:rgba(28,154,214,.08)}}
.run-link{{color:var(--ink);text-decoration:none;font-weight:600}}.run-link:hover{{color:var(--aqua-deep)}}
small{{display:block;font:11px ui-monospace,monospace;color:var(--muted);font-weight:400;margin-top:2px}}
td:nth-child(2),td:nth-child(3),td:nth-child(4){{font-size:13px;color:var(--muted)}}
.status{{font-size:11px;text-transform:capitalize;font-weight:600;padding:3px 10px;border-radius:999px}}
.status.done{{color:#0a6b47;background:rgba(43,201,143,.18)}}
.status.parked{{color:#8a5c0e;background:rgba(201,138,29,.18)}}
.status.open{{color:var(--aqua-deep);background:rgba(28,154,214,.16)}}
.status.abandoned{{color:#8a2f3f;background:rgba(232,99,122,.16)}}
.detail.glass{{margin-top:28px;padding:26px 28px}}
.detail-head{{display:flex;justify-content:space-between;align-items:flex-end}}
.eyebrow{{font-size:10px;letter-spacing:.12em;color:var(--aqua-deep);font-weight:700;margin:0 0 6px}}
.back{{font-size:13px;color:var(--aqua-deep);text-decoration:none;font-weight:600}}.back:hover{{text-decoration:underline}}
.task{{font-size:18px;margin:14px 0}}
.metadata{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px 20px;
  border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:15px 0;margin:16px 0 24px}}
dt{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}}dd{{margin:2px 0 0;overflow-wrap:anywhere}}
code{{font:12px ui-monospace,monospace}}.detail section{{margin:20px 0}}.detail h3{{font-size:14px;margin:0 0 6px;color:var(--aqua-deep)}}
ul{{padding-left:20px;margin:5px 0}}li{{margin:4px 0;overflow-wrap:anywhere}}
.muted,.empty{{color:var(--muted)}}.empty{{padding:25px 0}}
.error{{color:#8c243d;background:rgba(232,99,122,.16);padding:12px;border-radius:10px}}
.table-wrap{{padding-bottom:6px}}
@media(max-width:700px){{main{{padding:25px 16px 48px}}header.glass{{align-items:flex-start;flex-direction:column}}
  .table-wrap{{overflow-x:auto}}table{{min-width:660px}}.summary.glass{{gap:18px}}}}
</style></head><body><main>
<header class=glass><div><p class=brand>ClearStack / local run log</p><h1>Runs</h1></div>
<div class=head-right><span class=live id=live><span class=live-dot></span><span id=live-label>live</span></span>
<span class=local>{escape(bind_host)}</span></div></header>
<div class="summary glass"><div class=metric><strong>{len(runs)}</strong><span>runs</span></div>
<div class=metric><strong>{counts['open']}</strong><span>open</span></div><div class=metric><strong>{counts['done']}</strong><span>done</span></div>
<div class=metric><strong>{counts['parked']}</strong><span>parked</span></div>
{f'<div class=metric><strong>${total_cost:.2f}</strong><span>total cost</span></div>' if has_telemetry else ''}</div>
{"" if has_telemetry else '<div class="telemetry glass"><strong>Token and tool telemetry is not collected yet.</strong> No run in this log has it. Open a run detail to check once one does. Totals are not shown as zero.</div>'}
{error_html}<section class="panel glass"><div class=section-title><h2>Recent runs</h2><span class=count>newest first</span></div>{table}</section>
{detail_html}{missing}</main>
<script>
(function(){{
  var liveEl = document.getElementById("live");
  var liveLabel = document.getElementById("live-label");
  var refresh = function(){{
    fetch(location.href, {{cache: "no-store"}}).then(function(r){{ return r.text(); }}).then(function(html){{
      var next = new DOMParser().parseFromString(html, "text/html");
      var nextMain = next.querySelector("main");
      var curMain = document.querySelector("main");
      if (nextMain && curMain && nextMain.innerHTML !== curMain.innerHTML) {{
        curMain.innerHTML = nextMain.innerHTML;
      }}
    }}).catch(function(){{}});
  }};
  if (typeof EventSource === "undefined") {{
    liveLabel.textContent = "polling";
    setInterval(refresh, 4000);
    return;
  }}
  var es = new EventSource("/events");
  es.addEventListener("update", refresh);
  es.onopen = function(){{ liveEl.classList.remove("offline"); liveLabel.textContent = "live"; }};
  es.onerror = function(){{ liveEl.classList.add("offline"); liveLabel.textContent = "reconnecting"; }};
}})();
</script>
</body></html>"""


def _log_mtime():
    """Return the run log's mtime, or 0.0 when it does not exist yet."""
    try:
        return default_log_path().stat().st_mtime
    except OSError:
        return 0.0


class DashboardHandler(BaseHTTPRequestHandler):
    bind_host = "127.0.0.1"

    def do_GET(self):
        request = urlsplit(self.path)
        if request.path == "/events":
            self._serve_events()
            return
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
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _serve_events(self):
        """Server-Sent Events: push 'update' whenever the run log's mtime changes."""
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.end_headers()
            last_mtime = _log_mtime()
            last_ping = time.monotonic()
            while True:
                time.sleep(0.5)
                mtime = _log_mtime()
                if mtime != last_mtime:
                    last_mtime = mtime
                    self.wfile.write(b"event: update\ndata: {}\n\n")
                    self.wfile.flush()
                elif time.monotonic() - last_ping > 20:
                    last_ping = time.monotonic()
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

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
