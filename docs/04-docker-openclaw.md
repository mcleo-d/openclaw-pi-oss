# Docker and OpenClaw Setup

## Docker Installation

Docker Engine was installed on 2026-02-26 using the official install script:

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
```

- **Version installed:** Docker 29.2.1
- **Architecture:** arm64 (native, via `https://download.docker.com/linux/debian`)
- **Packages:** docker-ce, docker-ce-cli, containerd.io, docker-compose-plugin, docker-buildx-plugin

The `<username>` user was added to the `docker` group to allow running Docker commands without sudo:

```bash
sudo usermod -aG docker <username>
```

**Note:** Group membership takes effect on next login. In active SSH sessions, use `newgrp docker` or reconnect.

---

## OpenClaw Image

The official upstream image was pulled:

```bash
docker pull ghcr.io/openclaw/openclaw:latest
```

| Property | Value |
|---|---|
| Image | `ghcr.io/openclaw/openclaw:latest` |
| Created | 2026-02-28 (v2026.2.26) |
| Base | Debian (not Alpine — musl is incompatible with OpenClaw's native modules) |
| Node.js | v22.22.0 |
| Architecture | arm64 (multi-arch manifest) |

To update the image:

```bash
ssh <hostname> "docker pull ghcr.io/openclaw/openclaw:latest && cd ~/openclaw && docker compose up -d openclaw-gateway"
```

---

## Directory Structure

```text
~/openclaw/              # Compose project directory (chmod 750)
├── docker-compose.yml   # Hardened compose config (chmod 644)
└── .env                 # Secrets and config (chmod 600)

~/.openclaw/             # OpenClaw runtime data (chmod 700)
├── openclaw.json        # Provider config — Ollama URL, models, gateway settings (chmod 600)
└── workspace/           # Agent workspace (chmod 700)
```

---

## Environment File (`~/openclaw/.env`)

```env
# Docker image
OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:latest

# Directories
OPENCLAW_CONFIG_DIR=/home/<username>/.openclaw
OPENCLAW_WORKSPACE_DIR=/home/<username>/.openclaw/workspace

# Ports
OPENCLAW_GATEWAY_PORT=18789
OPENCLAW_BRIDGE_PORT=18790

# Gateway auth token (keep secret — read by OpenClaw from OPENCLAW_GATEWAY_TOKEN env var)
OPENCLAW_GATEWAY_TOKEN=<see file on Pi>

# Claude API credentials — not required when using Ollama. Populate if switching to Claude.
# CLAUDE_AI_SESSION_KEY=
# CLAUDE_WEB_SESSION_KEY=
# CLAUDE_WEB_COOKIE=
```

**Variables deliberately absent:**

- `OPENCLAW_GATEWAY_BIND` — removed. Gateway bind is configured in `openclaw.json` (`gateway.bind: "lan"`), not via .env.
- `OLLAMA_API_KEY` — removed. The API key is defined directly in `openclaw.json` (`models.providers.ollama.apiKey`), not passed via environment.

**To edit credentials on the Pi:**

```bash
ssh <hostname> "nano ~/openclaw/.env"
```

---

## docker-compose.yml (Hardened)

The compose file at `~/openclaw/docker-compose.yml` on the Pi contains the hardened configuration. Key security controls applied on top of the official defaults:

```yaml
services:
  openclaw-gateway:
    user: "node"                    # Non-root
    cap_drop: [ALL]                 # Zero capabilities
    security_opt:
      - no-new-privileges:true
    read_only: true                 # Read-only rootfs
    tmpfs:
      - /tmp:mode=1777,size=128m   # Writable /tmp only; cleared on restart
    mem_limit: 2g                  # Enforced via cgroup v2
    memswap_limit: 2g
    cpus: 2.0
    pids_limit: 500
    ports:
      - "127.0.0.1:18789:18789"    # Localhost only
      - "127.0.0.1:18790:18790"
    networks: [openclaw_net]
    extra_hosts:
      - "host.docker.internal:host-gateway"  # Resolves to Pi host IP — needed for Ollama
    environment:
      HOME: /home/node
      OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN}
      OPENCLAW_SANDBOX: non-main   # Agent tools in nested containers
      # Note: No Claude credential env vars — absent means unset (not empty string).
      # Add them here if switching from Ollama to Claude.
    command: ["node", "dist/index.js", "gateway"]
      # No --bind or --port CLI args: gateway settings are authoritative in openclaw.json.
      # CLI args would silently override the JSON config — keep one source of truth.
    healthcheck:                    # Liveness probe every 30s via /api/health
      ...
```

**`--bind lan` (0.0.0.0 inside container) is configured in `openclaw.json`, not as a CLI arg.** This is required: Docker port forwarding cannot reach a container-loopback socket. The host-side `127.0.0.1:18789:18789` port binding still restricts access to Pi-localhost only.

**Claude credential env vars are intentionally absent** (not set to empty strings). Passing empty strings differs from unset — some code paths treat them differently. If switching to Claude, add them to the environment section and uncomment them in `.env`.

The CLI service uses `profiles: [cli]` so it only starts when explicitly requested, never as a background daemon.

---

## Docker Network

An isolated bridge network was created:

```bash
docker network create \
  --driver bridge \
  --opt com.docker.network.bridge.enable_icc=false \
  --opt com.docker.network.bridge.enable_ip_masquerade=true \
  openclaw_net
```

- **ICC disabled:** Containers on this network cannot communicate with each other or with containers on other networks
- **IP masquerade enabled:** Outbound internet access works (required for AI API calls)

---

## Ollama Proxy (`ollama-proxy`)

OpenClaw does not connect directly to Ollama. A lightweight Python proxy sits between them on port <your-proxy-port> and fixes three issues that cannot be configured in OpenClaw itself:

| Problem | Proxy fix |
|---|---|
| OpenClaw sends `num_ctx=16384` → Ollama allocates 1.8 GiB KV cache → inference hangs (Pi 5 CPU hits a cache-miss cliff above ~4096 context) | Cap `options.num_ctx` at `PROXY_MAX_CTX` (4096) before forwarding |
| qwen3 thinking mode generates 200+ tokens per tool call (~50s/call) | Inject `"think": false` on every POST request |
| OpenClaw sends a ~4,600-token system prompt on every request → Pi 5 prefill takes ~248s (exceeds timeout) | Truncate system message to `PROXY_MAX_SYSTEM_CHARS` (500 chars, ~125 tokens) before forwarding |
| Malicious Telegram/Signal messages may contain prompt injection attacks | Two-layer detection: pattern matching (Gate 1) + LLM classifier (Gate 2) — see [Security Hardening doc](03-security-hardening.md#layer-8-prompt-injection-detection-ollama-proxy) |

The proxy is a systemd service that starts after Ollama:

```text
OpenClaw container
  │ http://host.docker.internal:<your-proxy-port>
  ▼
ollama-proxy  (0.0.0.0:<your-proxy-port>, /etc/ollama-proxy/proxy.py)
  │ http://127.0.0.1:11434
  ▼
Ollama  (127.0.0.1:11434, native systemd service — loopback only)
```

```bash
# Check status
ssh <hostname> "sudo systemctl status ollama-proxy --no-pager"

# View logs (shows num_ctx cap events)
ssh <hostname> "sudo journalctl -u ollama-proxy -n 20 --no-pager"

# Edit proxy logic
ssh <hostname> "sudo nano /etc/ollama-proxy/proxy.py"

# Edit injection patterns
ssh <hostname> "sudo nano /etc/ollama-proxy/patterns.conf"

# Edit tuning env vars
ssh <hostname> "sudo nano /etc/systemd/system/ollama-proxy.service"

# Reload after any change
ssh <hostname> "sudo systemctl daemon-reload && sudo systemctl restart ollama-proxy"
```

**Do not bypass the proxy** by changing `baseUrl` back to port 11434. Without the proxy, any chat message causes a multi-minute hang (or permanent freeze) due to the KV cache allocation issue, and all prompt injection protection is silently removed.

**Do not add injection patterns to `proxy.py`.** Patterns belong in `/etc/ollama-proxy/patterns.conf` only. `proxy.py` is published to the open source project; `patterns.conf` is internal and never published.

---

## OpenClaw Provider Config (`~/.openclaw/openclaw.json`)

OpenClaw is configured to use Ollama via the proxy. The config at `~/.openclaw/openclaw.json` (chmod 600):

```json
{
  "gateway": {
    "mode": "local",
    "port": 18789,
    "bind": "lan",
    "controlUi": {
      "allowedOrigins": ["http://localhost:18789", "http://127.0.0.1:18789"]
    }
  },
  "models": {
    "providers": {
      "ollama": {
        "baseUrl": "http://host.docker.internal:<your-proxy-port>",
        "apiKey": "ollama-local",
        "api": "ollama",
        "models": [
          {
            "id": "qwen3:1.7b-q4_K_M",
            "name": "Qwen3 1.7B (Q4_K_M, no-think)",
            "reasoning": false,
            "input": ["text"],
            "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
            "contextWindow": 32768,
            "maxTokens": 2048
          },
          {
            "id": "qwen2.5:3b-instruct-q4_K_M",
            "name": "Qwen 2.5 3B Instruct (Q4_K_M)",
            "reasoning": false,
            "input": ["text"],
            "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
            "contextWindow": 32768,
            "maxTokens": 2048
          }
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "ollama/qwen3:1.7b-q4_K_M",
        "fallbacks": ["ollama/qwen2.5:3b-instruct-q4_K_M"]
      }
    }
  }
}
```

Note: `contextWindow: 32768` exceeds OpenClaw's 16000-token minimum and silences the `low context window` log warning. The proxy intercepts the resulting `num_ctx=32768` and caps it to 4096 before Ollama ever sees it — no performance impact.

### How Docker reaches Ollama

Ollama runs natively on the Pi (not in Docker). The Docker container reaches it via the proxy:

1. `extra_hosts: host.docker.internal:host-gateway` in `docker-compose.yml` — Docker resolves `host.docker.internal` to the Pi's host IP as seen from inside the container
2. `baseUrl: http://host.docker.internal:<your-proxy-port>` — routes to the proxy, not Ollama directly
3. ufw rules allow the `openclaw_net` bridge interface on port <your-proxy-port> (rules 2, 5) before the global DENY (rules 3, 6)
4. `controlUi.allowedOrigins` in config — required because `--bind lan` is non-loopback

To verify connectivity end-to-end:

```bash
# Test proxy reachable from container network
ssh <hostname> "docker run --rm --network openclaw_net --add-host=host.docker.internal:host-gateway alpine/curl curl -s http://host.docker.internal:<your-proxy-port>/api/tags | python3 -c \"import sys,json; [print(m['name']) for m in json.load(sys.stdin)['models']]\""
```

---

## Starting and Managing OpenClaw

### Prerequisites

Ollama must be running (`systemctl is-active ollama`) and `~/.openclaw/openclaw.json` must be present. Claude API keys are not required when using Ollama only.

### Start the gateway

```bash
ssh <hostname> "cd ~/openclaw && docker compose up -d openclaw-gateway"
```

### Check status

```bash
ssh <hostname> "cd ~/openclaw && docker compose ps"
```

### View logs

```bash
ssh <hostname> "cd ~/openclaw && docker compose logs -f openclaw-gateway"
```

### Stop the gateway

```bash
ssh <hostname> "cd ~/openclaw && docker compose down"
```

### Run the interactive CLI (requires real TTY)

```bash
ssh -t <hostname> "cd ~/openclaw && docker compose --profile cli run --rm openclaw-cli"
```

### Restart the gateway

```bash
ssh <hostname> "cd ~/openclaw && docker compose restart openclaw-gateway"
```

### Access the web UI (via SSH tunnel)

The gateway is bound to Pi-localhost only. Access requires an SSH tunnel from your Mac.

#### One-time setup — `~/.ssh/config` on your Mac

Add these two entries (already configured — shown here for reference):

```text
# Regular SSH access
Host <hostname>
  HostName <hostname>.local
  User <username>
  IdentityFile ~/.ssh/id_ed25519
  ServerAliveInterval 60
  ServerAliveCountMax 3

# OpenClaw UI tunnel — run: ssh -N <hostname>-ui
Host <hostname>-ui
  HostName <hostname>.local
  User <username>
  IdentityFile ~/.ssh/id_ed25519
  LocalForward 18789 127.0.0.1:18789
  LocalForward 18790 127.0.0.1:18790
  ServerAliveInterval 60
  ServerAliveCountMax 3
  ExitOnForwardFailure yes
```

- **`ServerAliveInterval 60`** — sends a keepalive every 60 seconds; prevents the tunnel dropping silently during inactivity
- **`ExitOnForwardFailure yes`** — tunnel process exits cleanly if port forwarding fails, rather than hanging
- **Port 18789** — gateway WebSocket + Control UI
- **Port 18790** — agent bridge port (needed for advanced agent/tool features)

#### Every session

**Step 1 — Open the tunnel** (dedicated terminal tab, leave it open):

```bash
ssh -N <hostname>-ui
```

**Step 2 — Get the pre-authenticated URL:**

```bash
ssh <hostname> "cd ~/openclaw && docker compose exec openclaw-gateway node dist/index.js dashboard --no-open"
```

Outputs `http://127.0.0.1:18789/#token=<token>` — replace `127.0.0.1` with `localhost` and open it.

**First-time connection — device pairing:**
OpenClaw requires explicit approval for each new browser/device. After connecting with the token URL, the UI will show a "pairing required" screen. Approve from the Pi:

```bash
# List pending requests
ssh <hostname> "cd ~/openclaw && docker compose exec openclaw-gateway node dist/index.js devices list"

# Approve the pending request (copy the requestId UUID from the Request column)
ssh <hostname> "cd ~/openclaw && docker compose exec openclaw-gateway node dist/index.js devices approve <requestId>"
```

Once approved, the device is remembered — pairing is only required once per browser.

---

## Health Check

The container has a built-in health check probing `http://127.0.0.1:18789/api/health` every 30 seconds. To view health status:

```bash
# Via docker compose (preferred — no need to know the container name)
ssh <hostname> "cd ~/openclaw && docker compose ps"

# Via docker inspect (container name may vary)
ssh <hostname> "docker inspect \$(docker compose -f ~/openclaw/docker-compose.yml ps -q openclaw-gateway) --format '{{.State.Health.Status}}'"
```

---

## Troubleshooting

### Container exits immediately or restarts in a loop

Check logs for startup errors:

```bash
ssh <hostname> "cd ~/openclaw && docker compose logs openclaw-gateway"
```

Common causes and fixes:

| Error | Fix |
|---|---|
| `gateway.mode=local ... unset` | Add `"gateway": {"mode": "local"}` to `openclaw.json` |
| `Invalid --bind` | Valid values: `loopback`, `lan`, `tailnet`, `auto`, `custom`. Use `lan` for Docker port forwarding. |
| `non-loopback Control UI requires ... allowedOrigins` | Add `controlUi.allowedOrigins` to `openclaw.json` |
| `models.providers.ollama.models ... expected array` | Add `"models": [...]` array to Ollama provider in config |
| `models.providers.ollama.models.0 ... expected object` | Each model in the array must be an object with `id`, `name`, `reasoning`, `input`, `cost`, `contextWindow`, `maxTokens` fields |
| `fetch failed` after ~5 minutes, Ollama 500 error | OpenClaw is sending requests directly to Ollama (port 11434) with `num_ctx=16384`. This allocates a 1.8 GiB KV cache and inference hangs. Ensure `baseUrl` in `openclaw.json` points to **port <your-proxy-port>** (the proxy), not 11434. |
| `context window too small (N tokens). Minimum is 16000` | OpenClaw enforces a 16000-token minimum. `contextWindow` must be ≥ 16000. Use `32768` — the proxy caps the actual `num_ctx` sent to Ollama at 4096 regardless, so there is no performance cost. |
| Inference hangs even with proxy running | The proxy may have been bypassed, or Ollama has a stuck runner from a previous large-context request. Restart Ollama: `sudo systemctl restart ollama`. Confirm the proxy is capping: `sudo journalctl -u ollama-proxy -n 20`. |

### Control UI auth errors

| Error | Cause | Fix |
|---|---|---|
| `gateway token missing` | Token not entered in UI settings | Open the tokenized URL: `http://localhost:18789/#token=<token>` |
| `gateway token mismatch` | Wrong value pasted — likely included the `OPENCLAW_GATEWAY_TOKEN=` prefix | Paste only the hex value, not the full key=value string |
| `pairing required` | New browser/device has not been approved | Run `devices list` then `devices approve <requestId>` on the Pi (see above) |

### Cannot connect to gateway

Verify it's bound to localhost and the port is open:

```bash
ssh <hostname> "sudo ss -tlnp | grep 18789"
```

### Image is outdated

Pull the latest image and recreate the container:

```bash
ssh <hostname> "docker pull ghcr.io/openclaw/openclaw:latest && cd ~/openclaw && docker compose up -d openclaw-gateway"
```

### Out of disk space from Docker

```bash
# Remove unused images, stopped containers, dangling volumes
ssh <hostname> "docker system prune -f"
```

### Container is unhealthy or continuously restarting

```bash
# 1. Check status and health
ssh <hostname> "cd ~/openclaw && docker compose ps"

# 2. View recent logs
ssh <hostname> "cd ~/openclaw && docker compose logs --tail=50 openclaw-gateway"

# 3. Restart the gateway
ssh <hostname> "cd ~/openclaw && docker compose restart openclaw-gateway"

# 4. If restart doesn't help, check that Ollama and the proxy are up
ssh <hostname> "sudo systemctl status ollama ollama-proxy --no-pager"

# 5. If either is down, restart them first, then restart the gateway
ssh <hostname> "sudo systemctl restart ollama ollama-proxy"
sleep 10
ssh <hostname> "cd ~/openclaw && docker compose restart openclaw-gateway"
```

**Common cause:** The gateway health check probes `/api/health` every 30 seconds. If the agent subsystem crashes (not just the HTTP process), the container becomes unhealthy. A simple restart recovers it in all known cases — there is no persistent state that can be corrupted by a crash.
