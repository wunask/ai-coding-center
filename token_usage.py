"""Read-only local CLI token usage dashboard. No prompt contents are returned."""
import json
from collections import defaultdict
from pathlib import Path
from flask import Blueprint, jsonify, render_template

token_usage = Blueprint("token_usage", __name__)
HOME = Path.home()

def _rows(path):
    try:
        if path.stat().st_size > 100_000_000:
            return
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    yield json.loads(line)
                except (ValueError, TypeError):
                    continue
    except (OSError, PermissionError):
        return

def _num(v):
    return v if type(v) is int and v >= 0 else 0

def _claude():
    totals = defaultdict(int)
    count = 0
    base = HOME / ".claude" / "projects"
    if not base.exists():
        return dict(totals), count
    for path in base.glob("**/*.jsonl"):
        seen = set()
        for row in _rows(path):
            if row.get("type") != "assistant":
                continue
            msg = row.get("message") or {}
            usage = msg.get("usage") or {}
            if not usage:
                continue
            mid = msg.get("id") or row.get("uuid")
            if mid in seen:
                continue
            seen.add(mid)
            count += 1
            for key in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                totals[key] += _num(usage.get(key))
    totals["total_tokens"] = sum(totals.values())
    return dict(totals), count

def _codex():
    totals = defaultdict(int)
    count = 0
    paths = list((HOME / ".codex" / "sessions").glob("**/*.jsonl"))
    paths += list((HOME / ".codex" / "archived_sessions").glob("*.jsonl"))
    for path in paths:
        last = {}
        for row in _rows(path):
            payload = row.get("payload") or {}
            if row.get("type") != "event_msg" or payload.get("type") != "token_count":
                continue
            info = payload.get("info") or {}
            cumulative = info.get("total_token_usage") or {}
            if not cumulative:
                continue
            # Cumulative snapshots may repeat. Take positive differences only.
            current = {k: _num(cumulative.get(k)) for k in
                       ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_output_tokens")}
            if not last:
                count += 1
            for key in current:
                totals[key] += max(0, current[key] - last.get(key, 0))
            last = current
    totals["total_tokens"] = totals["input_tokens"] + totals["output_tokens"]
    return dict(totals), count

@token_usage.get("/tokens")
def tokens_page():
    return render_template("tokens.html")

@token_usage.get("/api/tokens")
def tokens_api():
    claude, c_count = _claude()
    codex, x_count = _codex()
    return jsonify(claude=claude, codex=codex, claude_records=c_count,
                   codex_sessions=x_count, note="Local CLI logs only; not provider billing. Claude output may be incomplete for some CLI versions.")
