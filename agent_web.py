"""Optional browser-based one-shot coding agents.

Disabled by default. Cloudflare mode verifies Access JWT signatures, issuer,
audience and expiration. Keep origin port private.
"""
import os
import secrets
import subprocess
import select
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
    if not _enabled():
        return False
    mode = os.environ.get("AGENT_WEB_MODE")
    if mode == "ssh-local":
        return (
            request.remote_addr in ("127.0.0.1", "::1")
            and request.host in ("127.0.0.1:9090", "localhost:9090",
                                 "127.0.0.1:8765", "localhost:8765")
        )
    if mode == "private-ip":
        # No application login: operator MUST restrict network access to trusted clients.
        # The request must arrive on the configured private interface, not via a public proxy.
        from ipaddress import ip_address, ip_network
        try:
            peer = ip_address(request.remote_addr)
            allowed = ip_network(os.environ.get("AGENT_ALLOWED_NETWORK", "127.0.0.1/32"), strict=False)
            return peer in allowed and ip_address(request.host.split(":")[0]) == ip_address(os.environ.get("AGENT_BIND_IP", "10.20.1.12"))
        except ValueError:
            return False
    if mode != "cloudflare":
        return False
    team = os.environ.get("CF_ACCESS_TEAM_DOMAIN", "").strip().rstrip("/")
    audience = os.environ.get("CF_ACCESS_AUD", "").strip()
    if not team or not audience:
        return False
    # Restrict key retrieval to the configured Cloudflare Access team domain.
    if team.startswith("https://"):
        issuer = team
    elif "://" not in team:
        issuer = "https://" + team
    else:
        return False
    from urllib.parse import urlsplit
    host = urlsplit(issuer).hostname or ""
    if not host.endswith(".cloudflareaccess.com") or host.count(".") < 2:
        return False
    token = request.headers.get("Cf-Access-Jwt-Assertion") or request.cookies.get("CF_Authorization")
    if not token:
        return False
    try:
        import jwt
        from jwt import PyJWKClient
        # JWKS client caches signing keys and refreshes on rotation.
        jwks = PyJWKClient(issuer + "/cdn-cgi/access/certs", cache_jwk_set=True, lifespan=300, timeout=5)
        key = jwks.get_signing_key_from_jwt(token).key
        jwt.decode(token, key, algorithms=["RS256"], audience=audience,
                   issuer=issuer, options={"require": ["exp", "iat", "iss", "aud", "sub"]})
        return True
    except Exception:
        return False


def _deny():
    return jsonify(error="Agent access denied. For private IP access, configure AGENT_WEB_MODE=private-ip, AGENT_BIND_IP and AGENT_ALLOWED_NETWORK, and restrict the VM firewall to trusted clients."), 403


def _origin_ok():
    # JS posts JSON with a non-simple header. Browsers cannot send that header
    # cross-origin without CORS preflight (which this app does not enable).
    return request.headers.get("X-AI-Coding-Center") == "1" and request.is_json


def _execute(job_id, executable, args, prompt):
    """Publish output incrementally while keeping the process bounded."""
    output = ""
    status = "error"
    proc = None
    try:
        _WORKDIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [str(executable), *args, prompt],
            cwd=str(_WORKDIR),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            env={**os.environ, "CI": "1", "TERM": "dumb"},
        )
        deadline = time.monotonic() + _TIMEOUT
        while True:
            if time.monotonic() >= deadline:
                proc.kill()
                proc.wait()
                output += "\\nTimed out."
                break
            readable, _, _ = select.select([proc.stdout], [], [], 0.15)
            if readable:
                chunk = os.read(proc.stdout.fileno(), 8192)
                if chunk:
                    output = (output + chunk.decode("utf-8", errors="replace"))[-50000:]
                    with _LOCK:
                        _JOBS[job_id]["output"] = output
                        _JOBS[job_id]["updated"] = time.time()
                elif proc.poll() is not None:
                    status = "done" if proc.returncode == 0 else "error"
                    break
            if proc.poll() is not None:
                # Drain remaining buffered output before finishing.
                remaining = proc.stdout.read() or b""
                output = (output + remaining.decode("utf-8", errors="replace"))[-50000:]
                status = "done" if proc.returncode == 0 else "error"
                break
        if proc.returncode and status == "error":
            output += f"\\nProcess exited with code {proc.returncode}."
    except Exception as exc:
        output = f"Agent execution failed: {type(exc).__name__}. Check server logs."
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
    with _LOCK:
        _JOBS[job_id]["status"] = status
        _JOBS[job_id]["output"] = output[-50000:]
        _JOBS[job_id]["updated"] = time.time()


@agent_web.get("/agents")
def agents_page():
    if os.environ.get("AGENT_WEB_MODE") in ("cloudflare", "private-ip") and not _authorized():
        return _deny()
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
