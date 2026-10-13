"""Read-only analytics from local Claude/Codex JSONL logs. No prompts exposed."""
import csv
import io
import json
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from flask import Blueprint, jsonify, render_template, Response, request

token_usage = Blueprint("token_usage", __name__)
HOME = Path(os.environ.get("AGENT_LOG_HOME", str(Path.home()))).expanduser()
FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "cached_input_tokens", "reasoning_output_tokens")
MAX_FILES = 1200
MAX_BYTES = 100_000_000

def _n(v):
    return v if type(v) is int and v >= 0 else 0

def _date(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None

def _read(path):
    try:
        if path.stat().st_size > MAX_BYTES:
            return
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        yield row
                except (ValueError, TypeError):
                    continue
    except OSError:
        return

def _files(root):
    try:
        if not root.is_dir():
            return []
        return sorted(root.glob("**/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:MAX_FILES]
    except OSError:
        return []

def _entry(provider, when, model, project, session, usage):
    if not when:
        return None
    d = {k: _n(usage.get(k)) for k in FIELDS}
    if provider == "claude":
        d["total_tokens"] = sum(d[k] for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    else:
        d["total_tokens"] = d["input_tokens"] + d["output_tokens"]
    return dict(provider=provider, timestamp=when.isoformat(), day=when.date().isoformat(),
                model=model or "Unknown", project=project or "Unknown", session=session or "Unknown", **d)

def _claude():
    rows = []
    root = HOME / ".claude" / "projects"
    for path in _files(root):
        seen = set()
        for r in _read(path):
            if r.get("type") != "assistant":
                continue
            msg = r.get("message") or {}
            if not isinstance(msg, dict):
                continue
            usage = msg.get("usage") or {}
            if not isinstance(usage, dict) or not usage:
                continue
            ident = msg.get("id") or r.get("uuid")
            # A message can be logged multiple times as a streamed update.
            if ident and ident in seen:
                continue
            if ident:
                seen.add(ident)
            when = _date(r.get("timestamp"))
            project = (r.get("cwd") or path.parent.name)
            session = r.get("sessionId") or path.stem
            entry = _entry("claude", when, msg.get("model"), project, session, usage)
            if entry:
                rows.append(entry)
    return rows

def _codex():
    rows = []
    paths = _files(HOME / ".codex" / "sessions") + _files(HOME / ".codex" / "archived_sessions")
    for path in paths[:MAX_FILES]:
        last = {k: 0 for k in FIELDS}
        model = "Unknown"
        project = "Unknown"
        session = path.stem
        for r in _read(path):
            typ = r.get("type")
            p = r.get("payload") or {}
            if not isinstance(p, dict):
                continue
            if typ == "session_meta":
                session = (p.get("id") or session)
                project = (p.get("cwd") or project)
            elif typ == "turn_context":
                model = p.get("model") or model
            elif typ == "event_msg" and p.get("type") == "token_count":
                info = p.get("info") or {}
                cumulative = info.get("total_token_usage") or {}
                if not isinstance(cumulative, dict) or not cumulative:
                    continue
                current = {k: _n(cumulative.get(k)) for k in ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_output_tokens")}
                # Reset counters may occur; a reset starts a new segment.
                delta = {k: (v - last[k] if v >= last[k] else v) for k, v in current.items()}
                last.update(current)
                if not delta["input_tokens"] and not delta["output_tokens"]:
                    continue
                entry = _entry("codex", _date(r.get("timestamp")), model, project, session, delta)
                if entry:
                    rows.append(entry)
    return rows

def _collect():
    return sorted(_claude() + _codex(), key=lambda r: r["timestamp"], reverse=True)

def _analytics(rows, period):
    now = datetime.now(timezone.utc)
    cutoff = {"7d": 7, "30d": 30, "90d": 90}.get(period)
    if cutoff:
        start = (now - timedelta(days=cutoff)).date().isoformat()
        rows = [r for r in rows if r["day"] >= start]
    totals = defaultdict(int)
    providers = defaultdict(lambda: defaultdict(int))
    models = defaultdict(lambda: defaultdict(int))
    projects = defaultdict(lambda: defaultdict(int))
    sessions = {}
    days = defaultdict(lambda: defaultdict(int))
    for r in rows:
        for k in (*FIELDS, "total_tokens"):
            totals[k] += r[k]
            providers[r["provider"]][k] += r[k]
        models[(r["provider"], r["model"])]["tokens"] += r["total_tokens"]
        models[(r["provider"], r["model"])]["events"] += 1
        projects[(r["provider"], r["project"])]["tokens"] += r["total_tokens"]
        projects[(r["provider"], r["project"])]["events"] += 1
        key = (r["provider"], r["session"])
        if key not in sessions:
            sessions[key] = {"provider": r["provider"], "session": r["session"], "project": r["project"], "model": r["model"], "last_seen": r["timestamp"], "tokens": 0, "events": 0}
        sessions[key]["tokens"] += r["total_tokens"]
        sessions[key]["events"] += 1
        days[r["day"]][r["provider"]] += r["total_tokens"]
    def rank(table, field):
        return sorted([{"provider": p, field: name, **dict(v)} for (p, name), v in table.items()], key=lambda x: x["tokens"], reverse=True)[:50]
    timeline = [{"date": day, "claude": d["claude"], "codex": d["codex"], "total": d["claude"] + d["codex"]} for day, d in sorted(days.items())]
    recent = [{k: r[k] for k in ("provider", "timestamp", "model", "project", "session", "total_tokens", "input_tokens", "output_tokens")} for r in rows[:40]]
    return dict(period=period, totals=dict(totals), providers={k: dict(v) for k,v in providers.items()},
                models=rank(models, "model"), projects=rank(projects, "project"),
                sessions=sorted(sessions.values(), key=lambda s:s["last_seen"], reverse=True)[:60],
                timeline=timeline, recent=recent, events=len(rows),
                note="Local CLI log counts only. Not billing, remaining quota or authoritative provider usage. Some FCC logs may not be available in these paths.")

@token_usage.get("/tokens")
def tokens_page():
    return render_template("tokens.html")

@token_usage.get("/api/tokens")
def tokens_api():
    period = request.args.get("period", "30d")
    if period not in ("7d", "30d", "90d", "all"):
        return jsonify(error="Invalid period"), 400
    return jsonify(_analytics(_collect(), period))

@token_usage.get("/api/tokens/export.csv")
def tokens_export():
    period = request.args.get("period", "30d")
    if period not in ("7d", "30d", "90d", "all"):
        return jsonify(error="Invalid period"), 400
    data = _analytics(_collect(), period)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "claude_tokens", "codex_tokens", "total_tokens"])
    for r in data["timeline"]:
        writer.writerow([r["date"], r["claude"], r["codex"], r["total"]])
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="ai-token-usage.csv"'})
