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

from clearstack.token_view import render_tokens_page


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
        focuses = [event for event in events if event.get("event") == "focus"]
        start = starts[0] if starts else {}
        end = ends[-1] if ends else None
        runs.append({
            "id": run_id,
            "start": start,
            "end": end,
            "events": events,
            "started_at": start.get("ts", ""),
            "status": end.get("status", "open") if end else "open",
            "parent_run_id": start.get("parent_run_id"),
            "spawned_by": start.get("spawned_by"),
            "current_focus": focuses[-1].get("text") if focuses else None,
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


_DONUT_COLORS = (
    "#139ad6", "#1fae6e", "#d99412", "#e0556e", "#7b5fe0", "#2bb8b0", "#c25fd1", "#5b8fd6",
)


def _donut_section(title, breakdown, limit=8):
    """A CSS conic-gradient donut plus a legend, for a name->count breakdown.

    Returns "" when there is nothing to chart, so callers can splice it in
    unconditionally. The top `limit` names are shown individually; the rest
    collapse into one "other" slice so the chart stays readable.
    """
    total = sum(breakdown.values())
    if not total:
        return ""
    items = sorted(breakdown.items(), key=lambda kv: kv[1], reverse=True)
    top, rest = items[:limit], items[limit:]
    if rest:
        top.append(("other", sum(n for _, n in rest)))
    stops = []
    legend = []
    angle = 0.0
    for i, (name, count) in enumerate(top):
        color = _DONUT_COLORS[i % len(_DONUT_COLORS)]
        pct = count / total * 100
        next_angle = angle + pct
        stops.append(f"{color} {angle:.2f}% {next_angle:.2f}%")
        angle = next_angle
        legend.append(
            f'<li><span class=donut-swatch style="background:{color}"></span>'
            f'{escape(str(name))}<span class=donut-count>{count} · {pct:.0f}%</span></li>'
        )
    gradient = ", ".join(stops)
    heading = f"<h3>{escape(title)}</h3>" if title else ""
    return f"""<div class=donut-wrap>
      {heading}
      <div class=donut-body>
        <div class=donut-chart style="background:conic-gradient({gradient})">
          <div class=donut-hole><strong>{total}</strong><span>calls</span></div>
        </div>
        <ul class=donut-legend>{''.join(legend)}</ul>
      </div>
    </div>"""


def _aggregate_tool_breakdown(runs):
    """Sum tool_breakdown across every run that has telemetry."""
    totals = {}
    for run in runs:
        telemetry = (run["end"] or {}).get("telemetry") if run["end"] else None
        if not telemetry:
            continue
        for name, count in (telemetry.get("tool_breakdown") or {}).items():
            totals[name] = totals.get(name, 0) + count
    return totals


def _telemetry_section(end):
    telemetry = end.get("telemetry") if end else None
    if not telemetry:
        return "<section><h3>Telemetry</h3><p class=muted>Not collected for this run.</p></section>"
    tokens = telemetry.get("tokens") or {}
    cost = telemetry.get("cost_usd")
    cost_text = f"${cost:.4f}" if isinstance(cost, (int, float)) else "—"
    model = telemetry.get("model")
    model_row = f"<div><dt>Model</dt><dd>{escape(str(model))}</dd></div>" if model else ""
    rows = "".join(f"""<div><dt>{escape(label)}</dt><dd>{_format_tokens(tokens.get(key, 0))}</dd></div>"""
                    for label, key in (("Input", "input"), ("Output", "output"),
                                        ("Cache read", "cache_read"), ("Cache write", "cache_write")))
    return f"""<section><h3>Telemetry · {escape(str(telemetry.get('source') or 'unknown'))}</h3>
      <dl class=metadata>{model_row}{rows}
        <div><dt>Tool calls</dt><dd>{_format_tokens(telemetry.get('tool_calls'))}</dd></div>
        <div><dt>Cost</dt><dd>{escape(cost_text)}</dd></div>
      </dl>
      {_donut_section('Tool calls by type', telemetry.get('tool_breakdown') or {})}
    </section>"""


def _focus_callout(run):
    focus = run.get("current_focus")
    if not focus:
        return ""
    return (f'<div class="telemetry glass focus-callout">'
            f"<strong>Current focus</strong><p>{escape(str(focus))}</p></div>")


def _detail(run, runs_by_id):
    start = run["start"]
    end = run["end"] or {}
    notes = [event.get("text", "") for event in run["events"] if event.get("event") == "note"]
    note_html = "".join(f"<li>{escape(str(note))}</li>" for note in notes)
    if not note_html:
        note_html = "<li class=muted>No decision notes recorded.</li>"
    parent, children = _run_family(run, runs_by_id)
    parent_html = ""
    if parent:
        parent_task = escape(str(parent["start"].get("task") or "Untitled run"))
        parent_html = (f'<p class=lineage>Spawned by <a href="/?run={escape(parent["id"], quote=True)}#detail">'
                        f"{parent_task}</a></p>")
    children_html = ""
    if children:
        items = "".join(
            f'<li><a href="/?run={escape(c["id"], quote=True)}#detail">'
            f'{escape(str(c["start"].get("task") or "Untitled run"))}</a> '
            f'<span class="status {escape(c["status"])}">{escape(c["status"])}</span></li>'
            for c in children
        )
        children_html = f'<section><h3>Subagents ({len(children)})</h3><ul class=lineage-list>{items}</ul></section>'
    return f"""<section class="detail glass" id=detail>
      <div class=detail-head><div><p class=eyebrow>RUN DETAIL</p><h2>{escape(run['id'])}</h2></div>
      <a class=back href="/">All runs</a></div>
      {parent_html}
      <p class=task>{escape(str(start.get('task') or 'Untitled run'))}</p>
      {_focus_callout(run)}
      <dl class=metadata>
        <div><dt>Agent</dt><dd>{escape(str(start.get('agent') or 'Unknown'))}</dd></div>
        <div><dt>Started</dt><dd>{escape(_display_time(run['started_at']))}</dd></div>
        <div><dt>Duration</dt><dd data-duration data-started="{escape(str(run['started_at']), quote=True)}" data-status="{escape(str(run['status']), quote=True)}">{escape(_duration(run))}</dd></div>
        <div><dt>Status</dt><dd>{escape(str(run['status']))}</dd></div>
        <div><dt>Branch</dt><dd>{escape(str(start.get('branch') or '—'))}</dd></div>
        <div><dt>Commit</dt><dd><code>{escape(str(start.get('head') or '—'))}</code></dd></div>
      </dl>
      {_subagent_banner(run)}
      <section><h3>Decision notes</h3><ul>{note_html}</ul></section>
      {_telemetry_section(end)}
      {_claims('Verified', end.get('verified', []))}
      {_claims('Unverified', end.get('unverified', []))}
      {f"<section><h3>Needs</h3><p>{escape(str(end['needs']))}</p></section>" if end.get('needs') else ''}
      {f"<section><h3>Pull request</h3><p>{escape(str(end['pr']))}</p></section>" if end.get('pr') else ''}
      {children_html}
    </section>"""


def _build_run_tree(runs):
    """Order runs newest-root-first with each run's children following it, depth-first.

    A run whose parent_run_id does not match any run in this log (unknown
    parent, or the parent run lives in a different log) is treated as a root
    so no run silently disappears from the list.
    """
    by_id = {run["id"]: run for run in runs}
    children_of = {}
    roots = []
    for run in runs:
        parent_id = run.get("parent_run_id")
        if parent_id and parent_id in by_id:
            children_of.setdefault(parent_id, []).append(run)
        else:
            roots.append(run)

    ordered = []

    def visit(run, depth):
        ordered.append((run, depth))
        for child in children_of.get(run["id"], []):
            visit(child, depth + 1)

    for run in roots:
        visit(run, 0)
    return ordered


def _run_family(run, runs_by_id):
    """Return (parent_run, child_runs) for the detail view, parent may be None."""
    parent_id = run.get("parent_run_id")
    parent = runs_by_id.get(parent_id) if parent_id else None
    children = [r for r in runs_by_id.values() if r.get("parent_run_id") == run["id"]]
    children.sort(key=lambda r: r["started_at"])
    return parent, children


def _subagent_banner(run):
    if not run.get("parent_run_id"):
        return ""
    spawned_by = escape(str(run.get("spawned_by") or "a subagent"))
    return (f'<div class="telemetry glass subagent-banner">'
            f"<strong>Self-reported by {spawned_by}.</strong> "
            "This run's claims are a subagent's own report, not verified evidence, "
            "until the parent run's output confirms them.</div>")


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


_EVENT_LABELS = {"start": "started", "note": "noted", "focus": "focus", "end": "finished"}


def _event_summary(event, task_by_run):
    kind = event.get("event")
    task = task_by_run.get(event.get("run"), "Untitled run")
    if kind in ("note", "focus"):
        text = str(event.get("text") or "")
        return text if len(text) <= 140 else text[:137] + "…"
    if kind == "end":
        status = event.get("status") or "done"
        return f"{task} — {status}"
    return task


def _recent_events(runs, limit=12):
    """Flatten every run's events into one newest-first activity feed."""
    task_by_run = {run["id"]: str(run["start"].get("task") or "Untitled run") for run in runs}
    all_events = [event for run in runs for event in run["events"] if event.get("event") in _EVENT_LABELS]
    all_events.sort(key=lambda event: (event.get("ts") or "", event.get("run") or ""), reverse=True)
    return [
        {
            "ts": event.get("ts") or "",
            "run": event.get("run") or "",
            "kind": event.get("event"),
            "label": _EVENT_LABELS.get(event.get("event"), event.get("event")),
            "summary": _event_summary(event, task_by_run),
        }
        for event in all_events[:limit]
    ]


def _activity_feed(runs):
    events = _recent_events(runs)
    if not events:
        return "<p class=empty>No activity yet. Start a run with clear-mode to see it here.</p>"
    items = "".join(f"""<li class="activity-item kind-{escape(e['kind'])}">
      <span class=activity-dot></span>
      <div><span class=activity-label>{escape(e['label'])}</span>
      <a class=activity-link href="/?run={escape(e['run'], quote=True)}#detail">{escape(e['summary'])}</a>
      <time>{escape(_display_time(e['ts']))}</time></div>
    </li>""" for e in events)
    return f"<ul class=activity-list>{items}</ul>"


def _status_mix(counts, total):
    if not total:
        return ""
    order = (("open", "aqua"), ("done", "mint"), ("parked", "amber"), ("abandoned", "coral"))
    segments = "".join(
        f'<span class="mix-seg mix-{color}" style="flex:{counts[name]}" title="{counts[name]} {name}"></span>'
        for name, color in order if counts[name]
    )
    return f'<div class=status-mix>{segments}</div>'


def render_page(runs, selected_id=None, error=None, bind_host="127.0.0.1"):
    """Render one self-contained HTML page. All run data is escaped."""
    counts = {name: sum(run["status"] == name for run in runs) for name in ("open", "done", "parked", "abandoned")}
    runs_by_id = {run["id"]: run for run in runs}
    selected = runs_by_id.get(selected_id) if selected_id else None
    has_telemetry = any((run["end"] or {}).get("telemetry") for run in runs if run["end"])
    total_cost = sum(c for c in (_run_cost(run) for run in runs) if isinstance(c, (int, float)))
    rows = []
    for run, depth in _build_run_tree(runs):
        start = run["start"]
        task = escape(str(start.get("task") or "Untitled run"))
        agent = escape(str(start.get("agent") or "Unknown"))
        run_id = escape(run["id"], quote=True)
        status = escape(str(run["status"]))
        indent = f' style="padding-left:{14 + depth * 18}px"' if depth else ""
        lineage_mark = '<span class=lineage-mark title="subagent run">↳</span> ' if depth else ""
        focus_hint = (f'<small class=focus-hint>→ {escape(str(run["current_focus"]))}</small>'
                      if run["status"] == "open" and run.get("current_focus") else "")
        rows.append(f"""<tr>
          <td{indent}>{lineage_mark}<a class=run-link href="/?run={run_id}#detail">{task}<small>{run_id}</small>{focus_hint}</a></td>
          <td>{agent}</td><td>{escape(_display_time(run['started_at']))}</td>
          <td data-duration data-started="{escape(str(run['started_at']), quote=True)}" data-status="{status}">{escape(_duration(run))}</td><td><span class="status {status}">{status}</span></td>
          <td>{_format_cost_cell(run)}</td>
        </tr>""")
    if rows:
        table = """<div class=table-wrap><table><thead><tr><th>Task</th><th>Agent</th><th>Started</th><th>Duration</th><th>Status</th><th>Cost</th></tr></thead>
        <tbody>""" + "".join(rows) + "</tbody></table></div>"
    else:
        table = "<p class=empty>No runs recorded yet. Start a task with clear-mode to add one.</p>"

    error_html = f"<p class=error>{escape(error)}</p>" if error else ""
    detail_html = _detail(selected, runs_by_id) if selected else ""
    missing = f"<p class=empty>Run '{escape(selected_id)}' was not found.</p>" if selected_id and not selected else ""
    return f"""<!doctype html>
<html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>ClearStack runs</title>
<style>
:root{{
  --sky-top:#0d6fd6;--sky-mid:#3b9bef;--sky-low:#8fcdfb;--sky-horizon:#d8f0fd;
  --surface:rgba(255,255,255,.55);--surface-strong:rgba(255,255,255,.82);--border:rgba(255,255,255,.75);
  --ink:#0b3156;--muted:#3f6e8f;--line:rgba(11,49,86,.12);
  --aqua:#139ad6;--aqua-deep:#0a6fb5;--mint:#1fae6e;--coral:#e0556e;--amber:#d99412;
  --shadow:0 2px 3px rgba(9,56,97,.08),0 18px 34px -16px rgba(9,56,97,.5);
}}
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;
  background:
    radial-gradient(420px 420px at 88% 6%,rgba(255,255,255,.95),rgba(255,255,255,.25) 40%,rgba(255,255,255,0) 62%),
    linear-gradient(180deg,var(--sky-top) 0%,var(--sky-mid) 38%,var(--sky-low) 72%,var(--sky-horizon) 100%);
  background-attachment:fixed}}
main{{max-width:1280px;margin:0 auto;padding:44px 28px 72px}}
.glass{{background:
    radial-gradient(120% 70% at 30% -20%,rgba(255,255,255,.95),rgba(255,255,255,0) 60%),
    var(--surface);
  backdrop-filter:blur(16px) saturate(170%);-webkit-backdrop-filter:blur(16px) saturate(170%);
  border:1px solid var(--border);border-radius:20px;
  box-shadow:var(--shadow),inset 0 1px 0 rgba(255,255,255,.9);position:relative;overflow:hidden}}
header.glass{{display:flex;align-items:center;justify-content:space-between;gap:24px;padding:20px 26px;margin-bottom:24px}}
h1{{font-size:clamp(26px,4vw,38px);line-height:1;margin:0;letter-spacing:-.03em;font-weight:800;
  color:var(--aqua-deep);text-shadow:0 1px 0 rgba(255,255,255,.8)}}
.brand{{color:var(--aqua-deep);font-size:12px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;margin:0 0 8px}}
.head-right{{display:flex;align-items:center;gap:10px}}
.live{{display:flex;align-items:center;gap:7px;font:12px ui-monospace,monospace;color:var(--aqua-deep);font-weight:600;
  background:var(--surface-strong);border:1px solid var(--border);border-radius:999px;padding:6px 13px 6px 11px;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.9);transition:background-color .4s ease}}
.live-dot{{width:8px;height:8px;border-radius:50%;background:radial-gradient(circle at 35% 30%,#baffd8,var(--mint) 65%);
  box-shadow:0 0 6px rgba(31,174,110,.7)}}
.live.offline .live-dot{{background:radial-gradient(circle at 35% 30%,#ffd0d8,var(--coral) 65%);box-shadow:0 0 6px rgba(224,85,110,.7)}}
.live.flash{{background:rgba(19,154,214,.28)}}
.local{{font:11px ui-monospace,monospace;color:var(--aqua-deep);border:1px solid var(--border);background:var(--surface-strong);
  border-radius:999px;padding:6px 12px;white-space:nowrap;box-shadow:inset 0 1px 0 rgba(255,255,255,.9)}}
.summary.glass{{display:flex;gap:30px;padding:16px 24px;margin-bottom:18px;flex-wrap:wrap}}
.metric{{display:flex;align-items:baseline;gap:9px}}.metric strong{{font:800 22px ui-monospace,monospace;color:var(--aqua-deep);
  text-shadow:0 1px 0 rgba(255,255,255,.6)}}
.metric span{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}}
.status-mix{{display:flex;height:8px;border-radius:999px;overflow:hidden;margin:0 0 18px;
  box-shadow:inset 0 1px 2px rgba(9,56,97,.18)}}
.mix-seg{{min-width:3px}}
.mix-aqua{{background:linear-gradient(90deg,var(--aqua),var(--aqua-deep))}}
.mix-mint{{background:linear-gradient(90deg,#4fe3a0,var(--mint))}}
.mix-amber{{background:linear-gradient(90deg,#ffcf5c,var(--amber))}}
.mix-coral{{background:linear-gradient(90deg,#ff8a9c,var(--coral))}}
.telemetry.glass{{margin:0 0 18px;padding:13px 18px;border-left:4px solid var(--aqua);font-size:13px}}.telemetry strong{{font-weight:650}}
.donut-wrap h3{{font-size:14px;margin:0 0 10px;color:var(--aqua-deep)}}
.donut-body{{display:flex;align-items:center;gap:16px;flex-wrap:wrap}}
.donut-chart{{position:relative;flex:none;width:96px;height:96px;border-radius:50%;
  box-shadow:0 2px 6px rgba(9,56,97,.25),inset 0 1px 0 rgba(255,255,255,.4)}}
.donut-hole{{position:absolute;inset:18px;border-radius:50%;background:var(--surface-strong);
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.9)}}
.donut-hole strong{{font:800 16px ui-monospace,monospace;color:var(--ink)}}
.donut-hole span{{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}}
.donut-legend{{list-style:none;margin:0;padding:0;flex:1;min-width:140px;font-size:12px}}
.donut-legend li{{display:flex;align-items:center;gap:7px;padding:3px 0;color:var(--ink)}}
.donut-swatch{{flex:none;width:9px;height:9px;border-radius:3px}}
.donut-count{{margin-left:auto;color:var(--muted);font:11px ui-monospace,monospace;white-space:nowrap}}
.section-title{{display:flex;justify-content:space-between;align-items:baseline;margin:0 0 12px}}
h2{{font-size:18px;margin:0;letter-spacing:-.02em;color:var(--ink)}}.count{{font:11px ui-monospace,monospace;color:var(--muted)}}
.panel.glass{{padding:8px 10px 2px}}
table{{width:100%;border-collapse:collapse;text-align:left}}
th{{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;font-weight:700;padding:12px 14px;border-bottom:1px solid var(--line)}}
td{{padding:13px 14px;border-bottom:1px solid var(--line);vertical-align:top}}
tbody tr:hover{{background:rgba(19,154,214,.08)}}
.run-link{{color:var(--ink);text-decoration:none;font-weight:600}}.run-link:hover{{color:var(--aqua-deep)}}
small{{display:block;font:11px ui-monospace,monospace;color:var(--muted);font-weight:400;margin-top:2px}}
td:nth-child(2),td:nth-child(3),td:nth-child(4){{font-size:13px;color:var(--muted)}}
td:nth-child(4),td:nth-child(5){{white-space:nowrap}}
.status{{display:inline-flex;align-items:center;white-space:nowrap;font-size:11px;text-transform:capitalize;font-weight:700;padding:3px 11px;border-radius:999px;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.7)}}
.status.done{{color:#065a3b;background:linear-gradient(180deg,rgba(255,255,255,.6),rgba(31,174,110,.22))}}
.status.parked{{color:#7a4f06;background:linear-gradient(180deg,rgba(255,255,255,.6),rgba(217,148,18,.22))}}
.status.open{{color:var(--aqua-deep);background:linear-gradient(180deg,rgba(255,255,255,.6),rgba(19,154,214,.22))}}
.status.abandoned{{color:#7a1f32;background:linear-gradient(180deg,rgba(255,255,255,.6),rgba(224,85,110,.22))}}
.status.open::before{{content:"";display:inline-block;width:6px;height:6px;margin-right:6px;border-radius:50%;
  background:var(--aqua-deep);animation:status-pulse 1.6s ease-in-out infinite}}
@keyframes status-pulse{{0%,100%{{opacity:1}}50%{{opacity:.35}}}}
.columns{{display:grid;grid-template-columns:2.1fr 1fr;gap:20px;align-items:start}}
.side-column{{display:flex;flex-direction:column;gap:20px}}
.activity-panel{{padding-bottom:12px}}
.activity-list{{list-style:none;margin:0;padding:4px 4px 8px}}
.activity-item{{display:flex;gap:10px;padding:9px 6px;border-bottom:1px solid var(--line);font-size:13px}}
.activity-item:last-child{{border-bottom:none}}
.activity-item.kind-start .activity-dot{{background:var(--aqua-deep)}}
.activity-item.kind-note .activity-dot{{background:var(--muted)}}
.activity-item.kind-end .activity-dot{{background:var(--mint)}}
.activity-dot{{flex:none;width:7px;height:7px;margin-top:6px;border-radius:50%;box-shadow:0 0 4px currentColor}}
.activity-label{{display:block;font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.07em;font-weight:700}}
.activity-link{{display:block;color:var(--ink);text-decoration:none;overflow-wrap:anywhere}}
.activity-link:hover{{color:var(--aqua-deep)}}
.activity-item time{{display:block;font:11px ui-monospace,monospace;color:var(--muted);margin-top:2px}}
.activity-item.is-new{{animation:activity-in .6s ease}}
@keyframes activity-in{{0%{{background:rgba(19,154,214,.2)}}100%{{background:transparent}}}}
.detail.glass{{margin-top:26px;padding:24px 26px}}
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
.error{{color:#8c243d;background:rgba(224,85,110,.18);padding:12px;border-radius:10px}}
.table-wrap{{padding-bottom:6px}}
.lineage-mark{{color:var(--muted);font-weight:700}}
.lineage{{font-size:12px;color:var(--muted);margin:0 0 10px}}
.lineage a{{color:var(--aqua-deep);text-decoration:none}}.lineage a:hover{{text-decoration:underline}}
.lineage-list{{list-style:none;padding:0;margin:5px 0}}
.lineage-list li{{display:flex;align-items:center;gap:8px;padding:4px 0}}
.lineage-list a{{color:var(--ink);text-decoration:none}}.lineage-list a:hover{{color:var(--aqua-deep)}}
.subagent-banner{{border-left-color:var(--amber)}}
.focus-callout{{border-left-color:var(--mint)}}.focus-callout strong{{display:block;margin-bottom:3px}}.focus-callout p{{margin:0}}
.focus-hint{{color:var(--aqua-deep)!important;font-style:italic}}
.activity-item.kind-focus .activity-dot{{background:var(--amber)}}
@media(max-width:700px){{main{{padding:25px 16px 48px}}header.glass{{align-items:flex-start;flex-direction:column}}
  .table-wrap{{overflow-x:auto}}table{{min-width:660px}}.summary.glass{{gap:18px}}}}
@media(max-width:860px){{.columns{{grid-template-columns:1fr}}}}
</style></head><body><main>
<header class=glass><div><p class=brand>ClearStack / local run log</p><h1>Runs</h1></div>
<div class=head-right><a class=back href="/tokens">Token spend</a><span class=live id=live><span class=live-dot></span><span id=live-label>live</span></span>
<span class=local>{escape(bind_host)}</span></div></header>
<div class="summary glass"><div class=metric><strong>{len(runs)}</strong><span>runs</span></div>
<div class=metric><strong>{counts['open']}</strong><span>open</span></div><div class=metric><strong>{counts['done']}</strong><span>done</span></div>
<div class=metric><strong>{counts['parked']}</strong><span>parked</span></div>
{f'<div class=metric><strong>${total_cost:.2f}</strong><span>total cost</span></div>' if has_telemetry else ''}</div>
{_status_mix(counts, len(runs))}
{"" if has_telemetry else '<div class="telemetry glass"><strong>Token and tool telemetry is not collected yet.</strong> No run in this log has it. Open a run detail to check once one does. Totals are not shown as zero.</div>'}
{error_html}<div class=columns>
<section class="panel glass"><div class=section-title><h2>Recent runs</h2><span class=count>newest first</span></div>{table}</section>
<div class=side-column>
<section class="panel glass activity-panel"><div class=section-title><h2>Activity</h2><span class=count>live feed</span></div>{_activity_feed(runs)}</section>
{f'<section class="panel glass donut-panel"><div class=section-title><h2>Tool mix</h2><span class=count>across all runs</span></div>{_donut_section("", _aggregate_tool_breakdown(runs))}</section>' if has_telemetry else ''}
</div>
</div>
{detail_html}{missing}</main>
<script>
(function(){{
  var liveEl = document.getElementById("live");
  var liveLabel = document.getElementById("live-label");
  var formatDuration = function(seconds){{
    seconds = Math.max(0, Math.floor(seconds));
    var h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
    if (h) return h + "h " + String(m).padStart(2, "0") + "m";
    if (m) return m + "m " + String(s).padStart(2, "0") + "s";
    return s + "s";
  }};
  var tickDurations = function(){{
    document.querySelectorAll("[data-duration]").forEach(function(el){{
      if (el.dataset.status !== "open" || !el.dataset.started) return;
      var started = new Date(el.dataset.started).getTime();
      if (isNaN(started)) return;
      el.textContent = formatDuration((Date.now() - started) / 1000);
    }});
  }};
  var refresh = function(){{
    fetch(location.href, {{cache: "no-store"}}).then(function(r){{ return r.text(); }}).then(function(html){{
      var next = new DOMParser().parseFromString(html, "text/html");
      var nextMain = next.querySelector("main");
      var curMain = document.querySelector("main");
      if (nextMain && curMain && nextMain.innerHTML !== curMain.innerHTML) {{
        curMain.innerHTML = nextMain.innerHTML;
        tickDurations();
        var first = curMain.querySelector(".activity-item");
        if (first) {{
          first.classList.add("is-new");
          setTimeout(function(){{ first.classList.remove("is-new"); }}, 650);
        }}
      }}
    }}).catch(function(){{}});
  }};
  var flashLive = function(){{
    liveEl.classList.add("flash");
    setTimeout(function(){{ liveEl.classList.remove("flash"); }}, 500);
  }};
  setInterval(tickDurations, 1000);
  if (typeof EventSource === "undefined") {{
    liveLabel.textContent = "polling";
    setInterval(refresh, 4000);
    return;
  }}
  var es = new EventSource("/events");
  es.addEventListener("update", function(){{ flashLive(); refresh(); }});
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
        if request.path == "/tokens":
            self._serve_tokens()
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

    def _serve_tokens(self):
        page = render_tokens_page(bind_host=self.bind_host)
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        )
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
