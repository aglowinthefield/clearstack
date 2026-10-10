"""Read Kanban review outcomes and attribute runs using observed model usage."""

import json
import re
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

TASK = re.compile(r"kanban task (t_[0-9a-f]+)")


def _db(path):
    conn = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _payload(raw):
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def _run_usage(sources, runs, notes):
    """Join a session to one task/profile/run interval, including compression children.

    A configured session model is never used as evidence of actual execution.
    Duplicate session IDs in the default and profile databases are counted once.
    """
    sessions = {}
    for label, path in sources:
        if not Path(path).is_file():
            continue
        try:
            with closing(_db(path)) as conn:
                first = {r["session_id"]: r["content"] or "" for r in conn.execute(
                    "SELECT session_id, content FROM messages WHERE id IN "
                    "(SELECT MIN(id) FROM messages WHERE role='user' GROUP BY session_id)"
                )}
                models = defaultdict(set)
                try:
                    for row in conn.execute(
                        "SELECT session_id, model, billing_provider FROM session_model_usage "
                        "WHERE task='' AND api_call_count > 0"
                    ):
                        if row["model"] and row["model"] != "unknown":
                            models[row["session_id"]].add(
                                f"{row['billing_provider'] or 'unknown'}:{row['model']}"
                            )
                except sqlite3.Error as exc:
                    notes.append(f"{label}: actual model attribution unavailable ({exc})")
                for row in conn.execute("SELECT * FROM sessions"):
                    data = dict(row)
                    profile = data.get("profile_name") or label
                    key = (profile, data["id"])
                    data.update(profile=profile, first_user=first.get(data["id"], ""),
                                models=models[data["id"]])
                    sessions[key] = data
        except sqlite3.Error as exc:
            notes.append(f"{label}: review session data unavailable ({exc})")

    intervals = defaultdict(list)
    for key, run in runs.items():
        intervals[(run["task_id"], run["profile"])].append((key, run))
    usage = defaultdict(lambda: {"models": set(), "tokens": 0, "sessions": 0,
                                 "usage_complete": True})
    matched = {}

    def match(key, visiting):
        if key in matched:
            return matched[key]
        if key in visiting or key not in sessions:
            return None
        session = sessions[key]
        parent = session.get("parent_session_id")
        if parent:
            inherited = match((key[0], parent), visiting | {key})
            if inherited:
                matched[key] = inherited
                return inherited
        task = TASK.search(session["first_user"])
        candidates = []
        if task:
            for run_key, run in intervals[(task.group(1), key[0])]:
                if run["started_at"] <= session["started_at"] < (run["ended_at"] or float("inf")) + 1:
                    candidates.append(run_key)
        matched[key] = candidates[0] if len(candidates) == 1 else None
        return matched[key]

    for key, session in sessions.items():
        run_key = match(key, set())
        if run_key is None:
            continue
        entry = usage[run_key]
        entry["models"].update(session["models"])
        entry["sessions"] += 1
        tokens = sum(session.get(k) or 0 for k in
                     ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"))
        entry["tokens"] += tokens
        entry["usage_complete"] &= tokens > 0
    return usage


def _percent(n, denominator):
    return round(n * 100 / denominator, 1) if denominator else None


def _models(usage, run_key):
    return sorted(usage.get(run_key, {}).get("models", []))


def _attribution(models):
    return "unknown" if not models else "mixed" if len(models) > 1 else "observed"


def mine_reviews(sources, boards_dir, change_at=None):
    """Return review rates, sample sizes, pending counts, and time/usage to AI approval."""
    notes, runs, cards = [], {}, {}
    for path in sorted(Path(boards_dir).glob("*/kanban.db")):
        board = path.parent.name
        try:
            with closing(_db(path)) as conn:
                board_runs = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM task_runs")}
                board_events = conn.execute(
                    "SELECT * FROM task_events WHERE kind IN "
                    "('review_requested','changes_requested','review_reopened','completed','archived') "
                    "ORDER BY created_at,id"
                ).fetchall()
            runs.update({(board, rid): r for rid, r in board_runs.items()})
        except sqlite3.Error as exc:
            notes.append(f"{board}: review history unavailable ({exc})")
            continue
        for event in board_events:
            key = (board, event["task_id"])
            card = cards.setdefault(key, {"rounds": [], "human": [], "active": None,
                                          "human_active": None})
            payload = _payload(event["payload"])
            kind, at = event["kind"], event["created_at"]
            if kind == "review_requested" and payload.get("reviewer") != "tom":
                if card["active"] is not None:
                    card["active"]["outcome"] = "superseded"
                round_data = {"implementer": payload.get("implementer") or "unknown",
                              "reviewer": payload.get("reviewer") or "unknown",
                              "submit_run": (board, event["run_id"]), "review_run": None,
                              "submitted_at": at, "decided_at": None, "outcome": "pending"}
                card["rounds"].append(round_data)
                card["active"] = round_data
            elif kind == "review_requested" and payload.get("reviewer") == "tom":
                if card["active"] is not None:
                    human = {"outcome": "pending", "submitted_at": at, "decided_at": None}
                    card["active"].update(outcome="approved", decided_at=at,
                                          review_run=(board, event["run_id"]), human=human)
                    card["active"] = None
                    card["human"].append(human)
                    card["human_active"] = human
            elif kind in {"changes_requested", "review_reopened"}:
                if card["human_active"] is not None:
                    card["human_active"].update(outcome="returned", decided_at=at)
                    card["human_active"] = None
                elif card["active"] is not None and kind == "changes_requested":
                    card["active"].update(outcome="returned", decided_at=at,
                                          review_run=(board, event["run_id"]))
                    card["active"] = None
            elif kind == "completed" and card["human_active"] is not None:
                card["human_active"].update(outcome="completed", decided_at=at)
                card["human_active"] = None
            if kind in {"completed", "archived"}:
                if card["active"] is not None:
                    card["active"].update(outcome="closed_without_verdict", decided_at=at)
                    card["active"] = None
                if card["human_active"] is not None:
                    card["human_active"].update(outcome="closed_without_verdict", decided_at=at)
                    card["human_active"] = None

    usage = _run_usage(sources, runs, notes)
    cohorts, pairs = defaultdict(list), defaultdict(list)
    for (board, task), card in cards.items():
        if not card["rounds"]:
            continue
        rounds = card["rounds"]
        task_runs = {key: r for key, r in runs.items() if key[0] == board and r["task_id"] == task}
        start = min([r["started_at"] for r in task_runs.values()] + [rounds[0]["submitted_at"]])
        latest = max([r["decided_at"] or r["submitted_at"] for r in rounds]
                     + [h["decided_at"] or h["submitted_at"] for h in card["human"]])
        cohort = ("all" if change_at is None else "after" if start >= change_at
                  else "crossed_change" if latest >= change_at else "before")
        approvals = [r["decided_at"] for r in rounds if r["outcome"] == "approved"]
        card["seconds_to_approval"] = None
        card["tokens_to_approval"] = None
        if approvals:
            approved_at = min(approvals)
            card["seconds_to_approval"] = approved_at - start
            work = [key for key, r in task_runs.items()
                    if r["started_at"] < approved_at and r["profile"] != "tom"]
            if work and all(key in usage and usage[key]["usage_complete"] for key in work):
                card["tokens_to_approval"] = sum(usage[key]["tokens"] for key in work)
        cohorts[(cohort, board, rounds[0]["implementer"])].append(card)
        for index, round_data in enumerate(rounds):
            implementer_models = tuple(_models(usage, round_data["submit_run"]))
            reviewer_models = tuple(_models(usage, round_data["review_run"]))
            pairs[(cohort, board, round_data["implementer"], implementer_models,
                   round_data["reviewer"], reviewer_models)].append((index == 0, round_data))

    cohort_rows = []
    for (cohort, board, profile), group in sorted(cohorts.items()):
        first = [c["rounds"][0] for c in group]
        resolved = [r for r in first if r["outcome"] in {"approved", "returned"}]
        returned = sum(r["outcome"] == "returned" for r in resolved)
        human = [h for c in group for h in c["human"]]
        decided_human = [h for h in human if h["outcome"] in {"completed", "returned"}]
        human_returns = sum(h["outcome"] == "returned" for h in decided_human)
        seconds = [c["seconds_to_approval"] for c in group if c["seconds_to_approval"] is not None]
        tokens = [c["tokens_to_approval"] for c in group if c["tokens_to_approval"] is not None]
        cohort_rows.append({
            "cohort": cohort, "board": board, "implementer": profile, "cards": len(group),
            "first_reviews_resolved": len(resolved), "first_passbacks": returned,
            "unresolved_first_reviews": len(first) - len(resolved),
            "first_passback_pct": _percent(returned, len(resolved)),
            "pending_reviews": sum(r["outcome"] == "pending" for c in group for r in c["rounds"]),
            "avg_review_rounds_per_card": round(sum(len(c["rounds"]) for c in group) / len(group), 2),
            "human_reviews_resolved": len(decided_human), "human_passbacks": human_returns,
            "human_passback_pct": _percent(human_returns, len(decided_human)),
            "pending_human_reviews": sum(h["outcome"] == "pending" for h in human),
            "closed_human_reviews": sum(h["outcome"] == "closed_without_verdict" for h in human),
            "ai_approved_cards": len(seconds), "approvals_with_complete_usage": len(tokens),
            "median_seconds_to_ai_approval": median(seconds) if seconds else None,
            "median_tokens_to_ai_approval": median(tokens) if tokens else None,
        })
    pair_rows = []
    for (cohort, board, implementer, im, reviewer, rm), group in sorted(pairs.items()):
        resolved = [r for _, r in group if r["outcome"] in {"approved", "returned"}]
        first = [r for is_first, r in group if is_first and r["outcome"] in {"approved", "returned"}]
        returned = sum(r["outcome"] == "returned" for r in resolved)
        first_returns = sum(r["outcome"] == "returned" for r in first)
        human = [r["human"] for _, r in group if "human" in r]
        human_resolved = [h for h in human if h["outcome"] in {"completed", "returned"}]
        human_returns = sum(h["outcome"] == "returned" for h in human_resolved)
        pair_rows.append({
            "cohort": cohort, "board": board, "implementer": implementer, "reviewer": reviewer,
            "implementer_models": list(im), "implementer_attribution": _attribution(im),
            "reviewer_models": list(rm), "reviewer_attribution": _attribution(rm),
            "review_rounds": len(group), "resolved_reviews": len(resolved),
            "passbacks": returned, "passback_pct": _percent(returned, len(resolved)),
            "first_reviews_resolved": len(first), "first_passbacks": first_returns,
            "first_passback_pct": _percent(first_returns, len(first)),
            "pending_reviews": sum(r["outcome"] == "pending" for _, r in group),
            "human_reviews_resolved": len(human_resolved), "human_passbacks": human_returns,
            "human_passback_pct": _percent(human_returns, len(human_resolved)),
            "pending_human_reviews": sum(h["outcome"] == "pending" for h in human),
            "closed_human_reviews": sum(h["outcome"] == "closed_without_verdict" for h in human),
        })
    return {"change_at": change_at, "notes": notes, "cohorts": cohort_rows, "model_pairs": pair_rows}


def format_summary(report):
    lines = ["Review outcomes (MEASURED from Kanban events and model usage):"]
    if report["change_at"] is not None:
        stamp = datetime.fromtimestamp(report["change_at"], timezone.utc).isoformat()
        lines.append(f"  Comparison boundary: {stamp}")
        if not any(row["cohort"] == "after" for row in report["cohorts"]):
            lines.append("  No after-change review submissions yet.")
    if not report["cohorts"]:
        lines.append("  No implementation review submissions found.")
    for row in report["cohorts"]:
        pct = row["first_passback_pct"]
        lines.append(
            f"  {row['board']}/{row['implementer']} {row['cohort']}: "
            f"{row['first_passbacks']}/{row['first_reviews_resolved']} first-review passbacks "
            f"({str(pct) + '%' if pct is not None else 'unknown'}), "
            f"{row['pending_reviews']} pending; {row['avg_review_rounds_per_card']} rounds/card "
            f"(n={row['cards']})"
        )
        lines.append(
            f"    Human returns after AI approval: {row['human_passbacks']}/"
            f"{row['human_reviews_resolved']} resolved handoffs, "
            f"{row['pending_human_reviews']} pending. Median to first AI approval: "
            f"{row['median_seconds_to_ai_approval'] if row['median_seconds_to_ai_approval'] is not None else 'unknown'} "
            f"seconds (n={row['ai_approved_cards']}), "
            f"{row['median_tokens_to_ai_approval'] if row['median_tokens_to_ai_approval'] is not None else 'unknown'} "
            f"tokens (n={row['approvals_with_complete_usage']})."
        )
    for row in report["model_pairs"]:
        im = '+'.join(row["implementer_models"]) or "unknown"
        rm = '+'.join(row["reviewer_models"]) or "unknown"
        lines.append(f"  {row['board']} {row['cohort']} {row['implementer']} [{im}] reviewed by "
                     f"{row['reviewer']} [{rm}]: {row['passbacks']}/{row['resolved_reviews']} "
                     f"passbacks, {row['pending_reviews']} pending; "
                     f"human returns {row['human_passbacks']}/{row['human_reviews_resolved']}")
    lines.extend(f"  Note: {note}" for note in report["notes"])
    return '\n'.join(lines)
