# Mobile Agents (experimental)

This adds a responsive **/agents** chat page for Claude Code and Codex.
It runs **one-shot commands**, not persistent FCC browser sessions, and shows the
completed output after the command returns (polling while active).

## Security prerequisites

- Protect the **entire hostname** using Cloudflare Access with your own email OTP.
- Confirm protection in an incognito browser. Do not add a Bypass policy.
- Use a **separate, least-privilege Unix user/container** for coding agents, with
  access only to disposable project files. Coding agents can execute code and
  modify anything their Unix identity can access.
- Do not expose FCC Admin, FCC credentials, or a root shell.
- Keep the Flask/Gunicorn service bound to 127.0.0.1 behind the Cloudflare Tunnel.
- This simple Basic Auth is **additional protection**, not a replacement for
  Cloudflare Access. Use HTTPS and a unique long password.

## Ubuntu setup

First verify the installed wrappers support noninteractive invocation:

```bash
fcc-claude --help
fcc-codex --help
fcc-codex exec --help
```

This experimental backend currently invokes:

- `~/.local/bin/fcc-claude -p "PROMPT"`
- `~/.local/bin/fcc-codex exec "PROMPT"`

If the installed wrapper or upstream CLI doesn't support these arguments, the
agent will fail. Validate commands locally with harmless test prompts **before
enabling the web interface**. Do not add unsafe bypass-permission flags.

Create a dedicated workspace:

```bash
mkdir -p ~/mobile-coding
chmod 700 ~/mobile-coding
```

In the service environment set:

```bash
export AGENT_WORKDIR="$HOME/mobile-coding"
export AGENT_WEB_PASSWORD="REPLACE_WITH_UNIQUE_RANDOM_PASSWORD_AT_LEAST_16_CHARS"
export AGENT_WEB_ENABLED=1
```

Run the app under the designated nonprivileged account:

```bash
.venv/bin/gunicorn --bind 127.0.0.1:8765 app:app
```

Visit `https://YOUR-ACCESS-PROTECTED-DOMAIN/agents`. Your browser should
ask for username `agent` and the password you configured (in addition to
Cloudflare email OTP).

### Notes
- The endpoint is **disabled by default** and needs an additional password.
- Jobs are kept **in process memory**; restarting Gunicorn clears their history.
- Use **one Gunicorn worker** for this prototype because jobs are in-memory.
- One agent at a time; 180-second timeout; 4,000-character prompt limit.
- Output is **not streamed**; it displays after completion.
- It does not yet preserve agent conversations across runs or synchronize
  with FCC Code Sessions.
- No automatic changes to the user's existing `fcc_stats.py` integration.
- Protect other dashboard routes too: Basic Auth here only guards `/agents`
  and its API routes.
