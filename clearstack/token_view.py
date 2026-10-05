"""Token-spend analytics view for the ClearStack dashboard.

Reads the default Hermes state.db plus every profile state.db read-only
(kanban workers record usage in their profile's db, not the default one)
and renders a self-contained HTML page with headline totals, model
breakdowns, daily stacked bars, session-size buckets, surface breakdown,
top sessions, tool mix, and system-prompt overhead anatomy.
"""

from html import escape
from pathlib import Path
import sqlite3

from clearstack.theme import theme_head, theme_picker


def _state_db_path():
    return Path.home() / ".hermes" / "state.db"


def _profile_dbs_dir():
    return Path.home() / ".hermes" / "profiles"


def _db_sources():
    """Return [(label, path)] for the default db and every profile state.db."""
    sources = [("default", _state_db_path())]
    profiles = _profile_dbs_dir()
    if profiles.is_dir():
        for child in sorted(profiles.iterdir()):
            db = child / "state.db"
            if child.is_dir() and db.is_file():
                sources.append((child.name, db))
    return sources


_DAYS = 14


def _with_dbs(func):
    """Run *func(conn, label)* against each readable state db.

    Return (sources, results): sources is the list of labels actually read,
    results is the list of per-db return values in the same order.
    """
    sources = []
    results = []
    for label, db_path in _db_sources():
        if not db_path.is_file():
            continue
        try:
            uri = f"file:{db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=5.0)
            try:
                conn.execute("PRAGMA busy_timeout = 5000")
                results.append(func(conn, label))
                sources.append(label)
            finally:
                conn.close()
        except (OSError, sqlite3.Error):
            continue
    return sources, results


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
    return {
        "fresh_input": row[0],
        "output": row[1],
        "cache_read": row[2],
        "cache_write": row[3],
        "api_calls": row[4],
        "actual_cost": row[5],
        "estimated_cost": row[6],
    }


def _merge_headline(parts):
    out = {k: sum(p[k] for p in parts) for k in parts[0]}
    out["cost"] = out["actual_cost"] if out["actual_cost"] else out["estimated_cost"]
    out["cost_is_actual"] = bool(out["actual_cost"])
    return out


def _table_columns(conn, table):
    """Return column names so dashboard reads tolerate older Hermes databases."""
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _billing_rows(conn):
    """Read Hermes's recorded pricing provenance, without calling providers."""
    required = {"billing_provider", "billing_mode", "cost_status", "cost_source"}
    if not required <= _table_columns(conn, "session_model_usage"):
        return []
    return conn.execute(
        f"SELECT billing_provider, billing_mode, cost_status, cost_source,"
        f" SUM(api_call_count), SUM(input_tokens), SUM(output_tokens),"
        f" COALESCE(SUM(actual_cost_usd),0), COALESCE(SUM(estimated_cost_usd),0)"
        f" FROM session_model_usage"
        f" WHERE last_seen > strftime('%s','now','-{_DAYS} days')"
        f" GROUP BY billing_provider, billing_mode, cost_status, cost_source"
    ).fetchall()


def _merge_billing(parts):
    """Merge pricing rows while retaining the provenance that qualifies a cost."""
    merged = {}
    for rows in parts:
        for provider, mode, status, source, calls, fresh, output, actual, estimated in rows:
            key = (provider or "unknown provider", mode or "unclassified", status or "unknown", source or "none")
            value = merged.setdefault(key, [0, 0, 0, 0.0, 0.0])
            value[0] += calls or 0
            value[1] += fresh or 0
            value[2] += output or 0
            value[3] += actual or 0
            value[4] += estimated or 0
    groups = []
    for (provider, mode, status, source), (calls, fresh, output, actual, estimated) in sorted(merged.items()):
        included = mode == "subscription_included" or status == "included"
        amount = actual if status == "actual" else estimated
        groups.append({
            "provider": provider,
            "mode": mode,
            "status": status,
            "source": source,
            "calls": calls,
            "fresh": fresh,
            "output": output,
            "amount": amount if amount else None,
            "included": included,
        })
    return groups


def _billing_section(groups):
    if not groups:
        return (
            '<section class="billing"><h2>Billing and quota signals</h2>'
            '<p class=muted>Hermes has no recorded billing metadata in the last 14 days.</p></section>'
        )
    cards = []
    metered_spend = 0.0
    for group in groups:
        if group["included"]:
            price = "Included with subscription"
        elif group["amount"] is not None:
            price = f"{_fmt_cost(group['amount'])} {escape(group['status'])}"
            metered_spend += group["amount"]
        else:
            price = "Price unavailable"
        cards.append(
            '<article class=billing-card>'
            f'<h3>{escape(group["provider"])}</h3><p class=billing-price>{price}</p>'
            f'<p class=billing-meta>{escape(group["mode"])} · {escape(group["source"])}</p>'
            f'<p class=billing-meta>{_fmt_tok(group["fresh"])} fresh in · '
            f'{_fmt_tok(group["output"])} out · {group["calls"]} calls</p></article>'
        )
    return f"""<section class=billing>
      <div class=section-heading><h2>Billing and quota signals</h2><span>last {_DAYS} days</span></div>
      <div class=billing-grid>{''.join(cards)}</div>
      <div class=guardrail data-billing-spend="{metered_spend:.4f}">
        <label for=clearstack-spend-cap>Set a 14-day spend guardrail</label>
        <div><span>$</span><input id=clearstack-spend-cap type=number min=0 step=0.01 inputmode=decimal placeholder="No cap"></div>
        <p data-spend-guardrail>Set a cap to compare against recorded metered cost.</p>
      </div>
      <p class=quota-note>Provider quota remaining and reset times are not stored by Hermes. This view reads local pricing metadata only and makes no provider request.</p>
    </section>"""


def _by_model(conn):
    return conn.execute(
        f"SELECT model, SUM(input_tokens), SUM(output_tokens),"
        f" SUM(cache_read_tokens), SUM(api_call_count),"
        f" COALESCE(SUM(actual_cost_usd),0), COALESCE(SUM(estimated_cost_usd),0)"
        f" FROM session_model_usage"
        f" WHERE last_seen > strftime('%s','now','-{_DAYS} days')"
        f" GROUP BY model",
    ).fetchall()


def _merge_by_model(parts):
    merged = {}
    for rows in parts:
        for model, fresh, out, cr, calls, act, est in rows:
            m = merged.setdefault(model or "unknown", [0, 0, 0, 0, 0.0, 0.0])
            m[0] += fresh or 0
            m[1] += out or 0
            m[2] += cr or 0
            m[3] += calls or 0
            m[4] += act or 0
            m[5] += est or 0
    max_fresh = max((v[0] for v in merged.values()), default=0)
    return [
        {
            "model": model,
            "fresh": v[0],
            "out": v[1],
            "cache_read": v[2],
            "calls": v[3],
            "cost": (v[4] if v[4] else v[5]) or None,
            "width_pct": (v[0] / max_fresh * 100) if max_fresh else 0,
        }
        for model, v in sorted(merged.items(), key=lambda kv: -kv[1][0])
    ]


def _daily_stacked(conn):
    return conn.execute(
        f"SELECT date(datetime(s.started_at,'unixepoch')) as day,"
        f" smu.model, SUM(smu.input_tokens)"
        f" FROM session_model_usage smu"
        f" JOIN sessions s ON s.id = smu.session_id"
        f" WHERE s.started_at > strftime('%s','now','-{_DAYS} days')"
        f" GROUP BY day, smu.model",
    ).fetchall()


def _merge_daily(parts):
    days = {}
    for rows in parts:
        for day, model, fresh in rows:
            days.setdefault(day, {})
            days[day][model or "unknown"] = days[day].get(model or "unknown", 0) + (fresh or 0)
    day_max = max((sum(m.values()) for m in days.values()), default=0)
    _COLORS = ("#5b8def", "#e2b93b", "#4fae62", "#d2654f", "#8f6fc9", "#4fa8a8", "#c96a9a", "#999")
    model_colors = {}
    for day in sorted(days):
        for model in days[day]:
            if model not in model_colors:
                model_colors[model] = _COLORS[len(model_colors) % len(_COLORS)]
    return [
        {
            "day": day,
            "total": sum(models.values()),
            "segments": [
                {
                    "model": model,
                    "fresh": fresh,
                    "width_pct": (fresh / day_max * 100) if day_max else 0,
                    "color": model_colors[model],
                }
                for model, fresh in sorted(models.items(), key=lambda kv: -kv[1])
            ],
        }
        for day, models in sorted(days.items())
    ], list(model_colors.items())


_BUCKETS = ("<20 msgs", "20-49", "50-99", "100-199", "200+")


def _bucket_for(message_count):
    n = message_count or 0
    if n < 20:
        return 0
    if n < 50:
        return 1
    if n < 100:
        return 2
    if n < 200:
        return 3
    return 4


def _session_sizes(conn):
    return conn.execute(
        f"SELECT message_count, input_tokens, cache_read_tokens"
        f" FROM sessions"
        f" WHERE started_at > strftime('%s','now','-{_DAYS} days')",
    ).fetchall()


def _merge_size_buckets(parts):
    buckets = [
        {"label": label, "sessions": 0, "fresh": 0, "cache_read": 0}
        for label in _BUCKETS
    ]
    for rows in parts:
        for message_count, fresh, cr in rows:
            b = buckets[_bucket_for(message_count)]
            b["sessions"] += 1
            b["fresh"] += fresh or 0
            b["cache_read"] += cr or 0
    max_fresh = max((b["fresh"] for b in buckets), default=0)
    _COLORS = ("#5b8def", "#e2b93b", "#4fae62", "#d2654f", "#8f6fc9")
    for i, b in enumerate(buckets):
        b["width_pct"] = (b["fresh"] / max_fresh * 100) if max_fresh else 0
        b["color"] = _COLORS[i % len(_COLORS)]
    return buckets


def _by_surface(conn):
    return conn.execute(
        f" SELECT COALESCE(source,'unknown'), COUNT(*), SUM(input_tokens),"
        f" SUM(output_tokens), SUM(cache_read_tokens),"
        f" COALESCE(SUM(actual_cost_usd),0), COALESCE(SUM(estimated_cost_usd),0)"
        f" FROM sessions"
        f" WHERE started_at > strftime('%s','now','-{_DAYS} days')"
        f" GROUP BY source",
    ).fetchall()


def _merge_surface(parts, sources):
    """Group by (source, db label). Profile dbs get a 'source · profile' label."""
    merged = {}
    for rows, label in zip(parts, sources):
        for source, n, fresh, out, cr, act, est in rows:
            display = source if label == "default" else f"{source} · {label}"
            m = merged.setdefault(display, [0, 0, 0, 0, 0.0, 0.0])
            m[0] += n or 0
            m[1] += fresh or 0
            m[2] += out or 0
            m[3] += cr or 0
            m[4] += act or 0
            m[5] += est or 0
    max_fresh = max((v[1] for v in merged.values()), default=0)
    _COLORS = ("#5b8def", "#e2b93b", "#4fae62", "#d2654f", "#8f6fc9", "#4fa8a8", "#c96a9a")
    return [
        {
            "surface": display,
            "sessions": v[0],
            "fresh": v[1],
            "out": v[2],
            "cache_read": v[3],
            "cost": (v[4] if v[4] else v[5]) or None,
            "width_pct": (v[1] / max_fresh * 100) if max_fresh else 0,
            "color": _COLORS[i % len(_COLORS)],
        }
        for i, (display, v) in enumerate(
            sorted(merged.items(), key=lambda kv: -kv[1][1])[:15]
        )
    ]


def _top_sessions(conn, label):
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
            "db": label,
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
    return conn.execute(
        f" SELECT COALESCE(tool_name,'unknown'), COUNT(*)"
        f" FROM messages"
        f" WHERE timestamp > strftime('%s','now','-{_DAYS} days') AND role='tool'"
        f" GROUP BY tool_name",
    ).fetchall()


def _merge_tool_volume(parts):
    merged = {}
    for rows in parts:
        for tool, n in rows:
            merged[tool] = merged.get(tool, 0) + (n or 0)
    top = sorted(merged.items(), key=lambda kv: -kv[1])[:15]
    max_n = max((n for _, n in top), default=0)
    _COLORS = ("#5b8def", "#e2b93b", "#4fae62", "#d2654f", "#8f6fc9", "#4fa8a8", "#c96a9a", "#999")
    return [
        {
            "tool": tool,
            "count": n,
            "width_pct": (n / max_n * 100) if max_n else 0,
            "color": _COLORS[i % len(_COLORS)],
        }
        for i, (tool, n) in enumerate(top)
    ]


def _prompt_rows(conn):
    return conn.execute(
        " SELECT hash, LENGTH(prompt) FROM system_prompts"
    ).fetchall()


def _merge_prompt_overhead(parts):
    by_hash = {}
    for rows in parts:
        for h, chars in rows:
            by_hash[h] = max(by_hash.get(h, 0), chars or 0)
    top = sorted(by_hash.items(), key=lambda kv: -kv[1])[:6]
    max_chars = max((c for _, c in top), default=0)
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
            "label": _LABELS[i] if i < len(_LABELS) else f"prompt {h[:8]}",
            "chars": chars,
            "tokens_approx": int(chars / 4),
            "width_pct": (chars / max_chars * 100) if max_chars else 0,
            "color": _COLORS[i % len(_COLORS)],
        }
        for i, (h, chars) in enumerate(top)
    ], len(by_hash)


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
    def query(conn, label):
        return {
            "headline": _headline_totals(conn),
            "by_model": _by_model(conn),
            "daily": _daily_stacked(conn),
            "sizes": _session_sizes(conn),
            "surface": _by_surface(conn),
            "top_sessions": _top_sessions(conn, label),
            "tools": _tool_volume(conn),
            "prompts": _prompt_rows(conn),
            "billing": _billing_rows(conn),
        }

    sources, parts = _with_dbs(query)
    if not parts:
        return {}

    top_sessions = sorted(
        (r for p in parts for r in p["top_sessions"]),
        key=lambda r: -(r["fresh"] or 0),
    )[:15]

    prompts, prompt_count = _merge_prompt_overhead([p["prompts"] for p in parts])
    return {
        "sources": sources,
        "headline": _merge_headline([p["headline"] for p in parts]),
        "by_model": _merge_by_model([p["by_model"] for p in parts]),
        "daily": _merge_daily([p["daily"] for p in parts]),
        "buckets": _merge_size_buckets([p["sizes"] for p in parts]),
        "surface": _merge_surface([p["surface"] for p in parts], sources),
        "top_sessions": top_sessions,
        "tools": _merge_tool_volume([p["tools"] for p in parts]),
        "prompts": prompts,
        "prompt_count": prompt_count,
        "billing": _merge_billing([p["billing"] for p in parts]),
    }


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

    sources_note = (
        f'<div class="note">Reading {len(data["sources"])} state db(s): '
        f'{escape(", ".join(data["sources"]))}. Kanban worker usage lives in '
        "profile dbs and is folded into every section below.</div>"
    )

    cost_note = (
        '<div class="note">Cost data exists only for metered providers. '
        "Subscription-quota providers show volume as rate-limit pressure, not dollars. "
        "Output is typically under 15% of fresh tokens: the spend is context, not generation.</div>"
    )
    billing = _billing_section(data["billing"])

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
        f"<td>{escape(r['db'])}</td>"
        f"<td>{escape(r['started'])}</td><td>{r['msgs']}</td><td>{r['calls']}</td>"
        f"<td>{_fmt_tok(r['fresh'])}</td><td>{_fmt_tok(r['out'])}</td>"
        f"<td>{_fmt_tok(r['cache_read'])}</td><td>{_fmt_cost(r['cost'])}</td></tr>"
        for r in data["top_sessions"]
    )
    top_table = (
        f'<table><tr><th>title</th><th>source</th><th>db</th><th>started</th><th>msgs</th>'
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
        f"{data['prompt_count']} distinct prompt hash(es) across all state dbs — each distinct hash "
        f"is a cache-bust that re-writes the prompt cache.</div>"
    )

    sections = (
        f'<div class="cards">{h_cards}</div>{sources_note}{billing}{cost_note}'
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
  --sky-top:#232937;--sky-mid:#30394a;--sky-low:#465266;--sky-horizon:#667487;
  --surface:rgba(22,27,36,.78);--surface-strong:rgba(31,38,50,.94);--border:rgba(181,195,218,.20);
  --ink:#edf2fa;--muted:#aebbd0;--line:rgba(181,195,218,.16);
  --aqua:#79a9ff;--aqua-deep:#b7d0ff;--mint:#69c69a;--coral:#ef8795;--amber:#efba65;
  --shadow:0 2px 3px rgba(0,0,0,.20),0 18px 34px -16px rgba(0,0,0,.72);
}}
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;
  background:linear-gradient(160deg,var(--sky-top) 0%,var(--sky-mid) 42%,var(--sky-low) 100%);
  background-attachment:fixed}}
main{{max-width:1280px;margin:0 auto;padding:44px 28px 72px}}
.glass{{background:var(--surface);backdrop-filter:blur(16px) saturate(130%);-webkit-backdrop-filter:blur(16px) saturate(130%);
  border:1px solid var(--border);border-radius:12px;box-shadow:var(--shadow);position:relative;overflow:hidden}}
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
.billing{{margin:26px 0 20px;padding-top:1px;border-top:1px solid var(--line)}}
.section-heading{{display:flex;align-items:baseline;justify-content:space-between;gap:12px}}
.section-heading h2{{margin-bottom:10px}}.section-heading span{{font-size:12px;color:var(--muted)}}
.billing-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}}
.billing-card{{border:1px solid var(--border);border-radius:8px;padding:12px;background:var(--surface)}}
.billing-card h3{{margin:0;color:var(--ink);font-size:14px}}.billing-price{{margin:8px 0 4px;color:var(--aqua-deep);font-size:16px;font-weight:700}}.billing-meta{{margin:3px 0;color:var(--muted);font-size:12px}}
.guardrail{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:12px;padding:10px 12px;background:var(--surface);border-left:3px solid var(--aqua)}}
.guardrail label{{font-size:13px;font-weight:650}}.guardrail div{{display:flex;align-items:center;gap:4px;color:var(--muted)}}.guardrail input{{width:100px;padding:4px 6px;border:1px solid var(--border);border-radius:4px;background:var(--surface-strong);color:var(--ink)}}.guardrail p{{margin:0;color:var(--muted);font-size:12px}}
.quota-note{{margin:10px 0 0;color:var(--muted);font-size:12px}}
table{{border-collapse:collapse;width:100%;font-size:12.5px}}
th{{text-align:left;color:var(--muted);font-weight:600;padding:4px 8px;border-bottom:1px solid var(--line)}}
td{{padding:4px 8px;border-bottom:1px solid var(--line)}}
.muted{{color:var(--muted)}}
.back{{font-size:13px;color:var(--aqua-deep);text-decoration:none;font-weight:600}}
.back:hover{{text-decoration:underline}}
</style>{theme_head()}</head><body><main>
<header class=glass><div><p class=brand>ClearStack / token spend</p><h1>Token spend</h1></div>
<div class=head-right>{theme_picker()}<a class=back href="/">← Runs</a><span class=local>{escape(bind_host)}</span></div></header>
<section class="panel glass">{body}</section>
</main></body></html>"""
