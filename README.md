# AI Coding Center (prototype)

A mobile-friendly **private** companion dashboard for Free Claude Code (FCC).

## Install on Ubuntu `ai-agent`

```bash
cd ~/ai-coding-center
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/gunicorn --bind 127.0.0.1:8765 app:app
```

Open `http://127.0.0.1:8765` on the Ubuntu host, or forward to your Windows PC:

```powershell
ssh -N -L 8765:127.0.0.1:8765 ai@10.20.1.12
```

Then open `http://127.0.0.1:8765` on Windows. Requires SSH connectivity.

## Remote phone access

- **Do not** expose this service or the FCC Admin UI directly to the public internet.
- Configure Cloudflare Tunnel for a dedicated hostname pointing to `http://127.0.0.1:8765`, and enforce a Cloudflare Access policy limited to your email with OTP. This protects the dashboard, **not** the FCC Admin UI.
- For Claude Code, connect to the VM via a private SSH solution (e.g. Cloudflare WARP private network) and run `fcc-claude` in `tmux`.
- For Codex, use FCC's built-in browser Code Sessions through an appropriately secured, supported remote-access path. The FCC Admin UI is localhost-only; do not bypass that restriction with a public reverse proxy.

## Metrics: important limitation

The dashboard's SQLite database starts empty. **It does not automatically collect FCC token counts.** The NVIDIA remaining quota is also not available here. Integrating FCC request/response logs or a documented usage API is a separate step; do not interpret zero as actual usage. The `/api/stats` endpoint reports only ingested records.

## Security

No remote command execution, no credentials in the source, binds to loopback by default. Protect access before deployment. If used behind a proxy, configure the proxy to authenticate every request including `/api/stats`.
