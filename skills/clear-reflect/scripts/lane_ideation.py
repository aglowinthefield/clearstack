"""Lane-ideation detector for clear-reflect.

Fingerprints sessions from state.db, clusters by dominant signals over weekly
windows, and reports candidate lanes that pass four gates: coherent, recurrent,
volume, and misplaced.

Stdlib only. No third-party imports.
"""

import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Thresholds and tunables (named constants, not magic numbers)
# ---------------------------------------------------------------------------

MIN_SESSIONS = 3
MIN_TOKENS = 1000
WINDOW_DAYS = 7
JACCARD_THRESHOLD = 0.3
TOP_N_PER_SESSION = 10
DOMINANT_K = 5
COHERENCE_THRESHOLD = 0.5
MIN_SESSIONS_PER_WINDOW = 1
MAX_CLUSTER_REFINE_ITERS = 5

# Signals too common to distinguish a work type
SIGNAL_STOPLIST = frozenset({
    "cd", "ls", "grep", "cat", "sed", "echo", "pwd", "#", "true", "set", "export"
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def connect_db(path):
    """Open the state database read-only. Return (connection, note)."""
    if not path.exists():
        return None, f"state db not found at {path}"
    try:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn, None
    except sqlite3.Error as e:
        return None, f"could not open state db: {e}"


def parse_tool_calls(tool_calls_json):
    """Parse assistant tool_calls JSON into a list of (call_id, tool_name, arguments)."""
    if not tool_calls_json:
        return []
    try:
        calls = json.loads(tool_calls_json)
    except (ValueError, TypeError):
        return []
    parsed = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        call_id = call.get("id") or call.get("call_id") or ""
        func = call.get("function", {})
        if isinstance(func, dict):
            name = func.get("name", "")
            args = func.get("arguments", "{}")
            try:
                args = json.loads(args) if isinstance(args, str) else args
            except (ValueError, TypeError):
                args = {}
        else:
            name = call.get("name", "")
            args = call.get("arguments", {})
        parsed.append((call_id, name, args))
    return parsed


def extract_session_fingerprint(conn, session_id):
    """Return signal fingerprint for a single session.

    Dict keys:
      session_id, profile, tokens, repo, signals (dict[str, int]), timestamps (list[float])
    """
    cur = conn.execute(
        "SELECT profile_name, git_repo_root, input_tokens, output_tokens "
        "FROM sessions WHERE id = ?",
        (session_id,),
    )
    row = cur.fetchone()
    profile = row["profile_name"] if row else None
    repo = row["git_repo_root"] if row else None
    tokens = 0
    if row:
        tokens = (row["input_tokens"] or 0) + (row["output_tokens"] or 0)

    signals = defaultdict(int)
    timestamps = []
    home = str(Path.home())

    cur = conn.execute(
        "SELECT timestamp, tool_calls FROM messages "
        "WHERE session_id = ? AND role = 'assistant' AND tool_calls IS NOT NULL",
        (session_id,),
    )
    for row in cur:
        ts = row["timestamp"]
        if ts is not None:
            timestamps.append(ts)
        for _call_id, tool_name, args in parse_tool_calls(row["tool_calls"]):
            if not isinstance(args, dict):
                continue
            if tool_name == "terminal":
                cmd = args.get("command", "").strip()
                if cmd:
                    parts = cmd.split()
                    base = parts[0] if parts else ""
                    base = Path(base).name
                    if base and base not in SIGNAL_STOPLIST:
                        signals[f"bin:{base}"] += 1
            elif tool_name in ("read_file", "write_file", "patch", "search_files"):
                path = args.get("path", "")
                if path:
                    path = str(Path(path).expanduser())
                    if path.startswith(home):
                        path = "~" + path[len(home):]
                    p = Path(path)
                    parts = [part for part in p.parts if part not in ("", "/")]
                    if parts:
                        prefix = str(Path(*parts[:2])) if len(parts) >= 2 else parts[0]
                        if prefix:
                            signals[f"path:{prefix}"] += 1
            elif tool_name == "skill_view":
                name = args.get("name")
                if name:
                    signals[f"skill:{name}"] += 1
            elif tool_name == "skill_manage":
                ops = args.get("operations", [])
                if isinstance(ops, list):
                    for op in ops:
                        if isinstance(op, dict):
                            name = op.get("name")
                            if name:
                                signals[f"skill:{name}"] += 1

    return {
        "session_id": session_id,
        "profile": profile,
        "tokens": tokens,
        "repo": repo,
        "signals": dict(signals),
        "timestamps": timestamps,
    }


def collect_sessions(db_path):
    """Return a list of session fingerprints from a single state db."""
    conn, _ = connect_db(db_path)
    if conn is None:
        return []
    sessions = []
    try:
        has_sessions = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions'"
        ).fetchone()
        if not has_sessions:
            return []
        cur = conn.execute(
            "SELECT id FROM sessions WHERE id IS NOT NULL"
        )
        for row in cur:
            fp = extract_session_fingerprint(conn, row["id"])
            fp["source_db"] = str(db_path)
            if fp["signals"]:
                sessions.append(fp)
    finally:
        conn.close()
    return sessions


# ---------------------------------------------------------------------------
# Signal prevalence
# ---------------------------------------------------------------------------

def compute_ubiquitous_signals(sessions, max_prevalence=0.5):
    """Return a set of signals that appear in more than max_prevalence fraction of sessions."""
    if not sessions:
        return set()
    total = len(sessions)
    sig_counts = defaultdict(int)
    for s in sessions:
        for sig in s["signals"]:
            sig_counts[sig] += 1
    return {sig for sig, count in sig_counts.items() if count / total > max_prevalence}


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def cluster_sessions(sessions, top_n=TOP_N_PER_SESSION, threshold=JACCARD_THRESHOLD, dominant_k=DOMINANT_K, ubiquitous=None):
    """Greedy Jaccard clustering over session top-N signal sets.

    Returns a list of sets of session indices.
    """
    ubiquitous = ubiquitous or set()
    session_tops = []
    for s in sessions:
        sigs = s["signals"]
        if sigs:
            sorted_sigs = sorted(sigs, key=lambda k: (-sigs[k], k))
            tops = set(sorted_sigs[:top_n]) - ubiquitous
        else:
            tops = set()
        session_tops.append(tops)

    unclustered = set(range(len(sessions)))
    clusters = []
    used_signals = set()

    while unclustered:
        sig_counts = defaultdict(int)
        for i in unclustered:
            for sig in session_tops[i]:
                if sig not in used_signals:
                    sig_counts[sig] += 1

        if not sig_counts:
            break

        best_sig = max(sig_counts, key=lambda s: (sig_counts[s], s))
        used_signals.add(best_sig)

        cluster = {i for i in unclustered if best_sig in session_tops[i]}
        if len(cluster) < 2:
            continue

        for _ in range(MAX_CLUSTER_REFINE_ITERS):
            dom_counts = defaultdict(int)
            for i in cluster:
                for sig in session_tops[i]:
                    dom_counts[sig] += 1
            sorted_doms = sorted(dom_counts, key=lambda s: (-dom_counts[s], s))
            dominant = set(sorted_doms[:dominant_k]) - ubiquitous
            if not dominant:
                break

            new_cluster = set()
            for i in cluster:
                tops = session_tops[i]
                if not tops:
                    continue
                inter = len(tops & dominant)
                union = len(tops | dominant)
                if union and inter / union >= threshold:
                    new_cluster.add(i)

            if new_cluster == cluster:
                break
            cluster = new_cluster

        if len(cluster) >= MIN_SESSIONS:
            clusters.append(cluster)
            unclustered -= cluster

    return clusters


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def dominant_signals(cluster_indices, sessions, k=DOMINANT_K, ubiquitous=None):
    sig_counts = defaultdict(int)
    for i in cluster_indices:
        for sig, count in sessions[i]["signals"].items():
            sig_counts[sig] += count
    if ubiquitous:
        for sig in ubiquitous:
            sig_counts.pop(sig, None)
    sorted_sigs = sorted(sig_counts, key=lambda s: (-sig_counts[s], s))
    return sorted_sigs[:k]


def is_coherent(cluster_indices, sessions, dominant, threshold=COHERENCE_THRESHOLD):
    if not dominant:
        return False
    top_sig = dominant[0]
    cluster_count = sum(1 for i in cluster_indices if top_sig in sessions[i]["signals"])
    if cluster_count / len(cluster_indices) < threshold:
        return False
    # Distinguishing: the signal must be meaningfully more concentrated in the cluster
    global_count = sum(1 for s in sessions if top_sig in s["signals"])
    global_frac = global_count / len(sessions) if sessions else 1
    cluster_frac = cluster_count / len(cluster_indices)
    return cluster_frac > global_frac * 1.5


def windows_for_cluster(cluster_indices, sessions, min_ts, window_days=WINDOW_DAYS):
    windows = set()
    for i in cluster_indices:
        for ts in sessions[i]["timestamps"]:
            idx = int((ts - min_ts) // (window_days * 86400))
            windows.add(idx)
    return sorted(windows)


def is_recurrent(windows, min_consecutive=2):
    if len(windows) < min_consecutive:
        return False
    for i in range(len(windows) - min_consecutive + 1):
        if windows[i + min_consecutive - 1] - windows[i] == min_consecutive - 1:
            return True
    return False


def infer_domain_for_signals(dominant_signals, domains):
    """Return the domain name that best matches the dominant signals, or None."""
    domain_scores = defaultdict(int)
    for sig in dominant_signals:
        if sig.startswith("skill:"):
            skill_name = sig[6:]
            for domain_name, info in domains.items():
                if skill_name in info.get("skills", set()):
                    domain_scores[domain_name] += 1
        else:
            text = sig[4:] if ":" in sig else sig
            for domain_name, info in domains.items():
                for rx in info.get("signals", []):
                    if rx.search(text):
                        domain_scores[domain_name] += 1
                        break
    if not domain_scores:
        return None
    return max(domain_scores, key=lambda d: (domain_scores[d], d))


def is_misplaced(cluster_indices, sessions, inferred_domain, profile_domain_map):
    if inferred_domain is None:
        return True
    mismatch = 0
    for i in cluster_indices:
        profile = sessions[i]["profile"]
        profile_domain = profile_domain_map.get(profile)
        if profile_domain != inferred_domain:
            mismatch += 1
    return mismatch > len(cluster_indices) / 2


def derive_candidate_name(dominant_signals):
    if not dominant_signals:
        return "unknown"
    top = dominant_signals[0]
    name = top.split(":", 1)[1] if ":" in top else top
    return re.sub(r"[^a-zA-Z0-9_-]", "-", name).strip("-")


# ---------------------------------------------------------------------------
# Main detector
# ---------------------------------------------------------------------------

def mine_lane_ideation(domain_map, state_db_path, profile_dbs_dir):
    """Discover lane-split candidates from session fingerprints.

    Returns a dict with keys:
      note, candidate_count, candidates
    Each candidate has:
      name, dominant_signals, session_count, profiles, tokens, windows,
      inferred_domain, proposed_skills, proposed_signals
    """
    if domain_map is None:
        return {"note": "no domain map", "candidate_count": 0, "candidates": []}

    domains = domain_map.get("domains", {})
    profile_domain_map = domain_map.get("profile_domain", {})

    all_sessions = []
    all_sessions.extend(collect_sessions(state_db_path))
    if profile_dbs_dir.exists():
        for profile_dir in profile_dbs_dir.iterdir():
            db = profile_dir / "state.db"
            if db.exists():
                all_sessions.extend(collect_sessions(db))

    if not all_sessions:
        return {"note": "no sessions with signals", "candidate_count": 0, "candidates": []}

    # Global min timestamp for windowing
    all_timestamps = [ts for s in all_sessions for ts in s["timestamps"]]
    if not all_timestamps:
        return {"note": "no message timestamps", "candidate_count": 0, "candidates": []}
    min_ts = min(all_timestamps)

    ubiquitous = compute_ubiquitous_signals(all_sessions)
    clusters = cluster_sessions(all_sessions, ubiquitous=ubiquitous)

    candidates = []
    for cluster_indices in clusters:
        session_count = len(cluster_indices)
        tokens = sum(all_sessions[i]["tokens"] for i in cluster_indices)
        if session_count < MIN_SESSIONS and tokens < MIN_TOKENS:
            continue

        dom = dominant_signals(cluster_indices, all_sessions, ubiquitous=ubiquitous)
        if not is_coherent(cluster_indices, all_sessions, dom):
            continue

        windows = windows_for_cluster(cluster_indices, all_sessions, min_ts)
        if not is_recurrent(windows):
            continue

        inferred = infer_domain_for_signals(dom, domains)
        if not is_misplaced(cluster_indices, all_sessions, inferred, profile_domain_map):
            continue

        profiles_seen = sorted({all_sessions[i]["profile"] for i in cluster_indices if all_sessions[i]["profile"]})
        name = derive_candidate_name(dom)
        # Deduplicate name if needed
        existing_names = {c["name"] for c in candidates}
        suffix = 1
        base_name = name
        while name in existing_names:
            name = f"{base_name}-{suffix}"
            suffix += 1

        candidates.append({
            "name": name,
            "dominant_signals": dom,
            "session_count": session_count,
            "profiles": profiles_seen,
            "tokens": tokens,
            "windows": windows,
            "inferred_domain": inferred,
            "proposed_skills": [s[6:] for s in dom if s.startswith("skill:")],
            "proposed_signals": [s for s in dom if not s.startswith("skill:")],
        })

    return {
        "note": None,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def candidate_to_yaml(candidate):
    """Render a candidate as a paste-ready YAML block."""
    lines = []
    lines.append(f"  {candidate['name']}:")
    lines.append("    profiles: []")
    if candidate.get("proposed_skills"):
        lines.append("    skills:")
        for skill in candidate["proposed_skills"]:
            lines.append(f"      - {skill}")
    else:
        lines.append("    skills: []")
    if candidate.get("proposed_signals"):
        lines.append("    signals:")
        for sig in candidate["proposed_signals"]:
            body = sig.split(":", 1)[1] if ":" in sig else sig
            if sig.startswith("bin:"):
                lines.append(f"      - '\\b{body}\\b'")
            else:
                lines.append(f"      - '{body}'")
    else:
        lines.append("    signals: []")
    return "\n".join(lines)


def format_lane_ideation_summary(lane_ideation):
    """Return human-readable lines for the lane-ideation section."""
    lines = []
    note = lane_ideation.get("note")
    if note:
        lines.append(f"Lane ideation: {note}")
        return "\n".join(lines)

    lines.append(f"Lane ideation: {lane_ideation['candidate_count']} candidate(s)")
    for c in lane_ideation["candidates"]:
        lines.append(
            f"  {c['name']} — {c['session_count']} sessions, {c['tokens']} tokens, "
            f"dominant: {', '.join(c['dominant_signals'])}"
        )
        lines.append(f"    profiles: {', '.join(c['profiles'])}")
        lines.append(f"    inferred domain: {c['inferred_domain'] or 'unassigned'}")
    if lane_ideation["candidates"]:
        lines.append("Paste-ready candidate YAML:")
        for c in lane_ideation["candidates"]:
            lines.append(candidate_to_yaml(c))
    return "\n".join(lines)
