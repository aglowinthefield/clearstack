"""Token-spend analytics view for the ClearStack dashboard.

Reads Hermes state.db read-only and renders a self-contained HTML page
with headline totals, model breakdowns, daily stacked bars, session-size
buckets, surface breakdown, top sessions, tool mix, and system-prompt
overhead anatomy.
"""

from html import escape
from pathlib import Path
import sqlite3


def _state_db_path():
    return Path.home() / ".hermes" / "state.db"


_DAYS = 14


def _with_db(func):
    """Run *func* with a read-only state.db connection, or return empty dict on failure."""
    db_path = _state_db_path()
    if not db_path.is_file():
        return {}
    try:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        try:
            conn.execute("PRAGMA busy_timeout = 5000")
            return func(conn)
        finally:
            conn.close()
    except (OSError, sqlite3.Error):
        return {}


def _fmt_tok(n):
    if n is None:
        return "—"
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _fmt_cost(n):
    if n is None or n == 0:
        return "—"
    return f"${n:.2f}"


def _headline_totals(conn):
    row = conn.execute(
        f"SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0),"
        f" COALESCE(SUM(cache_read_tokens),0), COALESCE(SUM(cache_write_tokens),0),"
        f" COALESCE(SUM(api_call_count),0),"
        f" COALESCE(SUM(actual_cost_usd),0), COALESCE(SUM(estimated_cost_usd),0)"
        f" FROM session_model_usage WHERE last_seen > strftime('%s','now','-{_DAYS} days')",
    ).fetchone()
    fresh, out, cache_r, cache_w, calls, act_cost, est_cost = row
    cost = act_cost if act_cost else est_cost
    return {
        "fresh_input": fresh,
        "output": out,
        "cache_read": cache_r,
        "cache_write": cache_w,
        "api_calls": calls,
        "cost": cost,
        "cost_is_actual": bool(act_cost),
    }


def _by_model(conn):
    rows = conn.execute(
        f"SELECT model, SUM(input_tokens), SUM(output_tokens),"
        f" SUM(cache_read_tokens), SUM(api_call_count),"
        f" COALESCE(SUM(actual_cost_usd),0), COALESCE(SUM(estimated_cost_usd),0)"
        f" FROM session_model_usage"
        f" WHERE last_seen > strftime('%s','now','-{_DAYS} days')"
        f" GROUP BY model ORDER BY SUM(input_tokens) DESC",
    ).fetchall()
    max_fresh = max((r[1] for r in rows), default=0)
    return [
        {
            "model": r[0] or "unknown",
            "fresh": r[1],
            "out": r[2],
            "cache_read": r[3],
            "calls": r[4],
            "cost": (r[5] if r[5] else r[6]) or None,
            "width_pct": (r[1] / max_fresh * 100) if max_fresh else 0,
        }
        for r in rows
    ]


def _daily_stacked(conn):
    rows = conn.execute(
        f"SELECT date(datetime(s.started_at,'unixepoch')) as day,"
        f" smu.model, SUM(smu.input_tokens)"
        f" FROM session_model_usage smu"
        f" JOIN sessions s ON s.id = smu.session_id"
        f" WHERE s.started_at > strftime('%s','now','-{_DAYS} days')"
        f" GROUP BY day, smu.model"
        f" ORDER BY day, SUM(smu.input_tokens) DESC",
    ).fetchall()
    days = {}
    for day, model, fresh in rows:
        days.setdefault(day, []).append({"model": model or "unknown", "fresh": fresh})
    day_max = max(
        (sum(m["fresh"] for m in models) for models in days.values()), default=0
    )
    _COLORS = ("#5b8def", "#e2b93b", "#4fae62", "#d2654f", "#8f6fc9", "#4fa8a8", "#c96a9a", "#999")
    model_colors = {}
    color_idx = 0
    for day, models in sorted(days.items()):
        for m in models:
            if m["model"] not in model_colors:
                model_colors[m["model"]] = _COLORS[color_idx % len(_COLORS)]
                color_idx += 1
    return [
        {
            "day": day,
            "total": sum(m["fresh"] for m in models),
            "segments": [
                {
                    "model": m["model"],
                    "fresh": m["fresh"],
                    "width_pct": (m["fresh"] / day_max * 100) if day_max else 0,
                    "color": model_colors[m["model"]],
                }
                for m in models
            ],
        }
        for day, models in sorted(days.items())
    ], list(model_colors.items())


def _size_buckets(conn):
    rows = conn.execute(
        f"SELECT"
        f" CASE WHEN message_count < 20 THEN '<20 msgs'"
        f" WHEN message_count < 50 THEN '20-49'"
        f" WHEN message_count < 100 THEN '50-99'"
        f" WHEN message_count < 200 THEN '100-199'"
        f" ELSE '200+' END as bucket,"
        f" COUNT(*), SUM(input_tokens), SUM(cache_read_tokens)"
        f" FROM sessions"
        f" WHERE started_at > strftime('%s','now','-{_DAYS} days')"
        f" GROUP BY bucket"
        f" ORDER BY MIN(message_count)",
    ).fetchall()
    max_fresh = max((r[2] for r in rows), default=0)
    _COLORS = ("#5b8def", "#e2b93b", "#4fae62", "#d2654f", "#8f6fc9")
    return [
        {
            "label": r[0],
            "sessions": r[1],
            "fresh": r[2],
            "cache_read": r[3],
            "width_pct": (r[2] / max_fresh * 100) if max_fresh else 0,
            "color": _COLORS[i % len(_COLORS)],
        }
        for i, r in enumerate(rows)
    ]


def _by_surface(conn):
    rows = conn.execute(
        f" SELECT COALESCE(source,'unknown'), COUNT(*), SUM(input_tokens),"
        f" SUM(output_tokens), SUM(cache_read_tokens),"
        f" COALESCE(SUM(actual_cost_usd),0), COALESCE(SUM(estimated_cost_usd),0)"
        f" FROM sessions"
        f" WHERE started_at > strftime('%s','now','-{_DAYS} days')"
        f" GROUP BY source"
        f" ORDER BY SUM(input_tokens) DESC",
    ).fetchall()
    max_fresh = max((r[2] for r in rows), default=0)
    _COLORS = ("#5b8def", "#e2b93b", "#4fae62", "#d2654f", "#8f6fc9", "#4fa8a8", "#c96a9a")
    return [
        {
            "surface": r[0],
            "sessions": r[1],
            "fresh": r[2],
            "out": r[3],
            "cache_read": r[4],
            "cost": (r[5] if r[5] else r[6]) or None,
            "width_pct": (r[2] / max_fresh * 100) if max_fresh else 0,
            "color": _COLORS[i % len(_COLORS)],
        }
        for i, r in enumerate(rows)
    ]


def _top_sessions(conn):
    rows = conn.execute(
        f" SELECT COALESCE(title,display_name,id), COALESCE(source,'unknown'),"
        f" date(datetime(started_at,'unixepoch')), message_count, api_call_count,"
        f" input_tokens, output_tokens, cache_read_tokens, actual_cost_usd"
        f" FROM sessions"
        f" WHERE started_at > strftime('%s','now','-{_DAYS} days') AND input_tokens > 0"
        f" ORDER BY input_tokens DESC LIMIT 15",
    ).fetchall()
    return [
        {
            "title": r[0],
            "source": r[1],
            "started": r[2],
            "msgs": r[3],
            "calls": r[4],
            "fresh": r[5],
            "out": r[6],
            "cache_read": r[7],
            "cost": r[8],
        }
        for r in rows
    ]


def _tool_volume(conn):
    rows = conn.execute(
        f" SELECT COALESCE(tool_name,'unknown'), COUNT(*)"
        f" FROM messages"
        f" WHERE timestamp > strftime('%s','now','-{_DAYS} days') AND role='tool'"
        f" GROUP BY tool_name"
        f" ORDER BY COUNT(*) DESC LIMIT 15",
    ).fetchall()
    max_n = max((r[1] for r in rows), default=0)
    _COLORS = ("#5b8def", "#e2b93b", "#4fae62", "#d2654f", "#8f6fc9", "#4fa8a8", "#c96a9a", "#999")
    return [
        {
            "tool": r[0],
            "count": r[1],
            "width_pct": (r[1] / max_n * 100) if max_n else 0,
            "color": _COLORS[i % len(_COLORS)],
        }
        for i, r in enumerate(rows)
    ]


def _prompt_overhead(conn):
    rows = conn.execute(
        " SELECT hash, LENGTH(prompt) FROM system_prompts ORDER BY LENGTH(prompt) DESC LIMIT 6"
    ).fetchall()
    max_chars = max((r[1] for r in rows), default=0)
    _LABELS = (
        "tool schemas JSON (largest snapshot)",
        "base prompt, rules, workspace",
        "deferred tool catalog",
        "skills catalog",
        "MEMORY",
        "USER PROFILE",
    )
    _COLORS = ("#5b8def", "#e2b93b", "#4fae62", "#d2654f", "#8f6fc9", "#4fa8a8")
    return [
        {
            "label": _LABELS[i] if i < len(_LABELS) else f"prompt {r[0][:8]}",
            "chars": r[1],
            "tokens_approx": int(r[1] / 4),
            "width_pct": (r[1] / max_chars * 100) if max_chars else 0,
            "color": _COLORS[i % len(_COLORS)],
        }
        for i, r in enumerate(rows)
    ]


def _distinct_prompt_count(conn):
    row = conn.execute("SELECT COUNT(DISTINCT hash) FROM system_prompts").fetchone()
    return row[0] if row else 0


def _bar_row(label, width_pct, color, value, sub=""):
    return (
        f'<div class="brow"><span class="blabel">{escape(str(label))}</span>'
        f'<span class="btrack">'
        f'<span class="bfill" style="width:{width_pct:.1f}%;background:{color}"></span>'
        f'</span><span class="bval">{escape(str(value))}</span>'
        f'<span class="sub">{escape(str(sub))}</span></div>'
    )


def _drow(day, total, segments):
    track = "".join(
        f'<span style="width:{s["width_pct"]:.2f}%;background:{s["color"]}"'
        f' title="{escape(s["model"])}: {_fmt_tok(s["fresh"])}"></span>'
        for s in segments
    )
    return (
        f'<div class="drow"><span class="blabel">{escape(day)}</span>'
        f'<span class="btrack tall">{track}</span>'
        f'<span class="bval">{_fmt_tok(total)}</span></div>'
    )


def _collect_data():
    def query(conn):
        return {
            "headline": _headline_totals(conn),
            "by_model": _by_model(conn),
            "daily": _daily_stacked(conn),
            "buckets": _size_buckets(conn),
            "surface": _by_surface(conn),
            "top_sessions": _top_sessions(conn),
            "tools": _tool_volume(conn),
            "prompts": _prompt_overhead(conn),
            "prompt_count": _distinct_prompt_count(conn),
        }

    return _with_db(query)


def render_tokens_page(bind_host="127.0.0.1"):
    data = _collect_data()
    if not data:
        empty = (
            '<div class="note">No state.db found or it is unreadable. '
            "Token analytics require a local Hermes state.db.</div>"
        )
        return _tokens_html(empty, bind_host)

    headline = data["headline"]
    h_cards = (
        f'<div class="card"><b>{_fmt_tok(headline.get("fresh_input"))}</b><span>fresh input tokens</span></div>'
        f'<div class="card"><b>{_fmt_tok(headline.get("output"))}</b><span>output tokens</span></div>'
        f'<div class="card"><b>{_fmt_tok(headline.get("cache_read"))}</b><span>cache-read tokens</span></div>'
        f'<div class="card"><b>{_fmt_tok(headline.get("cache_write"))}</b><span>cache-write tokens</span></div>'
        f'<div class="card"><b>{_fmt_tok(headline.get("api_calls"))}</b><span>API calls</span></div>'
    )
    if headline.get("cost"):
        cost_label = "measured cost (Anthropic only)" if headline.get("cost_is_actual") else "estimated cost"
        h_cards += f'<div class="card"><b>{_fmt_cost(headline.get("cost"))}</b><span>{cost_label}</span></div>'

    cost_note = (
        '<div class="note">Cost data exists only for metered providers. '
        "Subscription-quota providers show volume as rate-limit pressure, not dollars. "
        "Output is typically under 15% of fresh tokens: the spend is context, not generation.</div>"
    )

    by_model_bars = "".join(
        _bar_row(
            m["model"],
            m["width_pct"],
            _model_color(i),
            _fmt_tok(m["fresh"]),
            f"out {_fmt_tok(m['out'])} · cache-read {_fmt_tok(m['cache_read'])} · {m['calls']} calls"
            + (f" · {_fmt_cost(m['cost'])}" if m["cost"] else ""),
        )
        for i, m in enumerate(data["by_model"])
    )

    daily_rows, legend = data["daily"]
    legend_html = " ".join(
        f'<span class="lg"><i style="background:{c}"></i>{escape(m)}</span>'
        for m, c in legend
    )
    daily_html = "".join(_drow(r["day"], r["total"], r["segments"]) for r in daily_rows)

    bucket_bars = "".join(
        _bar_row(
            b["label"],
            b["width_pct"],
            b["color"],
            _fmt_tok(b["fresh"]),
            f"{b['sessions']} sessions · cache-read {_fmt_tok(b['cache_read'])}",
        )
        for b in data["buckets"]
    )

    surface_bars = "".join(
        _bar_row(
            s["surface"],
            s["width_pct"],
            s["color"],
            _fmt_tok(s["fresh"]),
            f"{s['sessions']} sessions · out {_fmt_tok(s['out'])} · cache-read {_fmt_tok(s['cache_read'])}"
            + (f" · {_fmt_cost(s['cost'])}" if s["cost"] else ""),
        )
        for s in data["surface"]
    )

    top_rows = "".join(
        f"<tr><td>{escape(r['title'])}</td><td>{escape(r['source'])}</td>"
        f"<td>{escape(r['started'])}</td><td>{r['msgs']}</td><td>{r['calls']}</td>"
        f"<td>{_fmt_tok(r['fresh'])}</td><td>{_fmt_tok(r['out'])}</td>"
        f"<td>{_fmt_tok(r['cache_read'])}</td><td>{_fmt_cost(r['cost'])}</td></tr>"
        for r in data["top_sessions"]
    )
    top_table = (
        f'<table><tr><th>title</th><th>source</th><th>started</th><th>msgs</th>'
        f'<th>calls</th><th>fresh in</th><th>out</th><th>cache-read</th><th>cost</th></tr>{top_rows}</table>'
    ) if top_rows else "<p class=muted>No sessions with fresh input in this window.</p>"

    tool_bars = "".join(
        _bar_row(t["tool"], t["width_pct"], t["color"], f"{t['count']:,}")
        for t in data["tools"]
    )

    prompt_bars = "".join(
        _bar_row(
            p["label"],
            p["width_pct"],
            p["color"],
            f"{_fmt_tok(p['chars'])} chars",
            f"≈{_fmt_tok(p['tokens_approx'])} tok",
        )
        for p in data["prompts"]
    )
    prompt_note = (
        f'<div class="note">Every turn carries roughly '
        f"{_fmt_tok(data['prompts'][0]['tokens_approx'] if data['prompts'] else 0)} "
        f"tokens of fixed prompt when the largest snapshot is active. "
        f"{data['prompt_count']} distinct prompt hash(es) in state.db — each distinct hash "
        f"is a cache-bust that re-writes the prompt cache.</div>"
    )

    sections = (
        f'<div class="cards">{h_cards}</div>{cost_note}'
        f'<h2>Fresh input by model</h2><div class="bars">{by_model_bars}</div>'
        f'<h2>Fresh input per day, stacked by model</h2>'
        f'<div style="margin:6px 0">{legend_html}</div>'
        f'<div class="bars">{daily_html}</div>'
        f'<h2>Session-size buckets: where the volume lives</h2>'
        f'<div class="bars">{bucket_bars}</div>'
        f'<h2>By surface</h2><div class="bars">{surface_bars}</div>'
        f'<h2>Top sessions by fresh input</h2>{top_table}'
        f'<h2>Tool result volume (count, last {_DAYS}d)</h2>'
        f'<div class="bars">{tool_bars}</div>'
        f'<h2>Fixed per-turn overhead anatomy (chars)</h2>'
        f'<div class="bars">{prompt_bars}</div>{prompt_note}'
    )
    return _tokens_html(sections, bind_host)


_MODEL_COLORS = (
    "#5b8def", "#e2b93b", "#4fae62", "#d2654f", "#8f6fc9", "#4fa8a8", "#c96a9a", "#999"
)


def _model_color(i):
    return _MODEL_COLORS[i % len(_MODEL_COLORS)]


def _tokens_html(body, bind_host):
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Token spend · ClearStack</title><style>
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
.local{{font:11px ui-monospace,monospace;color:var(--aqua-deep);border:1px solid var(--border);background:var(--surface-strong);
  border-radius:999px;padding:6px 12px;white-space:nowrap;box-shadow:inset 0 1px 0 rgba(255,255,255,.9)}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0}}
.card{{background:var(--surface-strong);border:1px solid var(--border);border-radius:8px;padding:10px 16px;min-width:130px}}
.card b{{display:block;font-size:20px;color:var(--aqua-deep)}}
.card span{{color:var(--muted);font-size:12px}}
h2{{font-size:15px;margin:28px 0 10px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}}
.brow,.drow{{display:flex;align-items:center;gap:10px;margin:3px 0}}
.blabel{{width:230px;text-align:right;color:var(--ink);font-size:12.5px;flex:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.btrack{{flex:1;background:var(--line);border-radius:4px;height:14px;display:flex;overflow:hidden}}
.btrack.tall{{height:18px}}
.bfill{{display:block;height:100%}}
.btrack.tall span{{display:block;height:100%}}
.bval{{width:64px;color:var(--ink);font-size:12.5px;flex:none}}
.sub{{color:var(--muted);font-size:12px}}
.lg{{margin-right:14px;font-size:12px;color:var(--ink)}}
.lg i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}}
.note{{background:var(--surface-strong);border-left:3px solid var(--amber);padding:10px 14px;margin:10px 0;font-size:13px;color:var(--ink)}}
table{{border-collapse:collapse;width:100%;font-size:12.5px}}
th{{text-align:left;color:var(--muted);font-weight:600;padding:4px 8px;border-bottom:1px solid var(--line)}}
td{{padding:4px 8px;border-bottom:1px solid var(--line)}}
.muted{{color:var(--muted)}}
.back{{font-size:13px;color:var(--aqua-deep);text-decoration:none;font-weight:600}}
.back:hover{{text-decoration:underline}}
</style></head><body><main>
<header class=glass><div><p class=brand>ClearStack / token spend</p><h1>Token spend</h1></div>
<div class=head-right><a class=back href="/">← Runs</a><span class=local>{escape(bind_host)}</span></div></header>
<section class="panel glass">{body}</section>
</main></body></html>"""
