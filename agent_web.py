"""Optional browser-based one-shot coding agents.

Disabled by default. Supports local SSH-forward testing only. Never publish
local testing mode through a tunnel or reverse proxy.
"""
import os
import secrets
import subprocess
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

agent_web = Blueprint("agent_web", __name__)
_WORKDIR = Path(os.environ.get("AGENT_WORKDIR", str(Path.home() / "mobile-coding"))).resolve()
_JOBS = {}
_LOCK = threading.Lock()
_MAX_JOBS = 30
_MAX_PROMPT = 4000
_TIMEOUT = 180

# Fixed executable paths and argv: browser input is never interpolated into a shell.
_EXECUTABLES = {
    "claude": (Path.home() / ".local/bin/fcc-claude", ["-p", "--permission-mode", "plan"]),
    "codex": (Path.home() / ".local/bin/fcc-codex", ["exec", "--sandbox", "read-only"]),
}


def _enabled():
    return os.environ.get("AGENT_WEB_ENABLED") == "1"


def _authorized():
    # This mode is ONLY for direct SSH port forwarding to a loopback-bound
    # Gunicorn instance. It is NOT safe to expose through Cloudflare Tunnel.
    # Production authentication is intentionally not implemented yet.
    return (
        _enabled()
        and os.environ.get("AGENT_WEB_MODE") == "ssh-local"
        and request.remote_addr in ("127.0.0.1", "::1")
        and request.host in ("127.0.0.1:9090", "localhost:9090",
                             "127.0.0.1:8765", "localhost:8765")
    )


def _deny():
    return jsonify(error="Agents disabled. SSH-local testing requires AGENT_WEB_ENABLED=1 and AGENT_WEB_MODE=ssh-local; do not publish this service."), 403


def _origin_ok():
    # JS posts JSON with a non-simple header. Browsers cannot send that header
    # cross-origin without CORS preflight (which this app does not enable).
    return request.headers.get("X-AI-Coding-Center") == "1" and request.is_json


def _execute(job_id, executable, args, prompt):
    output = ""
    status = "error"
    try:
        _WORKDIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        proc = subprocess.run(
            [str(executable), *args, prompt],
            cwd=str(_WORKDIR),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=_TIMEOUT,
            env={**os.environ, "CI": "1", "TERM": "dumb"},
            check=False,
        )
        output = proc.stdout[-50000:]
        status = "done" if proc.returncode == 0 else "error"
        if proc.returncode:
            output += f"\nProcess exited with code {proc.returncode}."
    except subprocess.TimeoutExpired as exc:
        data = exc.stdout or b""
        output = (data.decode(errors="replace") if isinstance(data, bytes) else str(data))[-50000:] + "\nTimed out."
    except Exception as exc:
        output = f"Agent execution failed: {type(exc).__name__}. Check server logs."
    with _LOCK:
        _JOBS[job_id]["status"] = status
        _JOBS[job_id]["output"] = output
        _JOBS[job_id]["updated"] = time.time()


@agent_web.get("/agents")
def agents_page():
    return render_template("agents.html")


@agent_web.post("/api/agents/run")
def start_agent():
    if not _authorized():
        return _deny()
    if not _origin_ok():
        return jsonify(error="Invalid request"), 400
    data = request.get_json(silent=True) or {}
    agent = data.get("agent")
    prompt = data.get("prompt")
    if agent not in _EXECUTABLES or not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= _MAX_PROMPT:
        return jsonify(error="Choose an agent and enter up to 4,000 characters"), 400
    executable, args = _EXECUTABLES[agent]
    if not executable.is_file():
        return jsonify(error=f"{agent} executable is missing"), 503
    with _LOCK:
        if any(j["status"] == "running" for j in _JOBS.values()):
            return jsonify(error="Another agent is running. Try again after it finishes."), 409
        # Ensure bounded memory use; old responses are removed first.
        while len(_JOBS) >= _MAX_JOBS:
            oldest = min(_JOBS, key=lambda x: _JOBS[x]["updated"])
            _JOBS.pop(oldest)
        job_id = secrets.token_urlsafe(18)
        _JOBS[job_id] = {"status": "running", "output": "", "updated": time.time(), "agent": agent}
    threading.Thread(target=_execute, args=(job_id, executable, args, prompt), daemon=True).start()
    return jsonify(job_id=job_id), 202


@agent_web.get("/api/agents/jobs/<job_id>")
def get_agent(job_id):
    if not _authorized():
        return _deny()
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return jsonify(error="Job not found (possibly after service restart)"), 404
        return jsonify(job.copy())
