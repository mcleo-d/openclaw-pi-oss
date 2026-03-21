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

## Ollama Proxy

OpenClaw does not connect directly to Ollama. A lightweight Python proxy sits between them
and fixes issues that cannot be configured in OpenClaw itself. Two variants are provided —
choose based on your security requirements.

### Choosing a proxy variant

| Variant | Service | Fixes | Requires |
|---|---|---|---|
| **Minimal** (recommended starting point) | `openclaw-proxy` | think:false injection, num_ctx cap | Nothing — self-contained |
| **Enhanced** (higher security posture) | `ollama-proxy` | All minimal fixes + system prompt truncation + Gate 1 (pattern match) + Gate 2 (LLM classifier) injection detection | `patterns.conf` and `classifier-prompt.txt` (operator-supplied) |

Both proxy variants fix the two issues that block inference on constrained hardware:

| Problem | Proxy fix |
|---|---|
| OpenClaw sends `num_ctx` values that exceed safe KV cache limits → Ollama allocates too much RAM → inference hangs | Cap `options.num_ctx` at `PROXY_MAX_CTX` before forwarding |
| qwen3 thinking mode generates 200+ tokens per tool call (~50s/call) | Inject `"think": false` on every POST request |

The enhanced variant additionally fixes:

| Problem | Fix |
|---|---|
| OpenClaw sends a multi-thousand-token system prompt on every request → Pi 5 prefill takes hundreds of seconds (exceeds timeout) | Truncate system message to `PROXY_MAX_SYSTEM_CHARS` (500 chars, ~125 tokens) |
| Malicious messages may contain prompt injection attacks | Two-layer detection: pattern matching (Gate 1) + LLM classifier (Gate 2) — see [Security Hardening doc](03-security-hardening.md) |

### Architecture

```text
OpenClaw container
  │ http://host.docker.internal:<your-proxy-port>
  ▼
openclaw-proxy or ollama-proxy  (0.0.0.0:<your-proxy-port>)
  │ http://127.0.0.1:11434
  ▼
Ollama  (127.0.0.1:11434, native systemd service)
```

### Context window — two-value design

`contextWindow` in `openclaw.json` and `PROXY_MAX_CTX` in the proxy service are
intentionally different values and serve different purposes:

- **`contextWindow`** — metadata the gateway reads for eligibility. OpenClaw enforces a
  minimum of 16000 tokens; values below this block all inference with
  "context window too small". Set to `16384`.
- **`PROXY_MAX_CTX`** — the actual `num_ctx` cap sent to Ollama. This controls KV cache
  allocation and RAM usage. At `num_ctx=16384` the model uses ~5.5 GB RAM on a Pi 5
  (dangerously close to OOM on an 8 GB device). At `num_ctx=8192` it uses ~4.2 GB —
  safe margin. Set to `8192`.

Do not set `PROXY_MAX_CTX` to match `contextWindow` or you risk OOM on constrained hardware.

### Managing the proxy

```bash
# Check status (substitute openclaw-proxy or ollama-proxy)
ssh <hostname> "sudo systemctl status openclaw-proxy --no-pager"

# View logs (shows num_ctx cap events and think:false injections)
ssh <hostname> "sudo journalctl -u openclaw-proxy -n 20 --no-pager"

# Edit tuning env vars
ssh <hostname> "sudo nano /etc/systemd/system/openclaw-proxy.service"

# Reload after any change
ssh <hostname> "sudo systemctl daemon-reload && sudo systemctl restart openclaw-proxy"
```

For the enhanced variant (`ollama-proxy`), also:

```bash
# Edit injection patterns
ssh <hostname> "sudo nano /etc/ollama-proxy/patterns.conf"
```

**Do not bypass the proxy** by changing `baseUrl` back to port 11434. Without the proxy,
any chat message may cause a multi-minute hang due to uncapped KV cache allocation.

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
            "id": "qwen3:4b-q4_K_M",
            "name": "Qwen3 4B (Q4_K_M, no-think)",
            "reasoning": false,
            "input": ["text"],
            "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
            "contextWindow": 16384,
            "maxTokens": 512
          }
        ]
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "ollama/qwen3:4b-q4_K_M",
        "fallbacks": []
      }
    }
  }
}
```

**`contextWindow` and `maxTokens` values explained:**

- `contextWindow: 16384` satisfies OpenClaw's 16000-token minimum eligibility check. The proxy caps the actual KV cache (`PROXY_MAX_CTX`) independently — typically at 8192 on a Pi 5. See [two-value design](#context-window--two-value-design) above.
- `maxTokens: 512` is a practical cap for ~4 t/s hardware. At 512 tokens, worst-case generation is ~128s — within the gateway's LLM timeout. Setting this higher risks timeout before completion.

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

> **Why a tunnel is required:** The browser dashboard uses the Web Crypto API for device
> identity. Web Crypto requires a [secure context](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts)
> — either HTTPS or `localhost`. Accessing the dashboard via a LAN IP over HTTP (e.g.
> `http://192.168.x.x:18789`) triggers the error "control ui requires device identity".
> The SSH tunnel forwards port 18789 to `localhost` on your Mac, satisfying the secure
> context requirement without needing TLS. Use `http://localhost:18789` — not the Pi's IP.

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

> **Important:** The gateway health check reports `healthy` as soon as the HTTP process is up — it does **not** verify that inference is working. Always confirm the proxy is reachable from the container (`curl http://host.docker.internal:<your-proxy-port>/api/tags` from inside the container) before trusting a `healthy` status after a network or UFW change.

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
| `fetch failed` after ~5 minutes, Ollama 500 error | OpenClaw is sending requests directly to Ollama (port 11434) with an uncapped `num_ctx`. Ensure `baseUrl` in `openclaw.json` points to **port <your-proxy-port>** (the proxy), not 11434. |
| `context window too small (N tokens). Minimum is 16000` | OpenClaw enforces a 16000-token minimum on the `contextWindow` metadata field. Set `contextWindow: 16384` in `openclaw.json`. The proxy caps the actual KV cache via `PROXY_MAX_CTX` (default 8192) — the two values serve different purposes. |
| Inference hangs even with proxy running | The proxy may have been bypassed, or Ollama has a stuck runner from a previous large-context request. Restart Ollama: `sudo systemctl restart ollama`. Confirm the proxy is capping: `sudo journalctl -u openclaw-proxy -n 20` (or `ollama-proxy` if using the enhanced variant). |

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
ssh <hostname> "sudo systemctl status ollama openclaw-proxy --no-pager"
# (substitute ollama-proxy if using the enhanced variant)

# 5. If either is down, restart them first, then restart the gateway
ssh <hostname> "sudo systemctl restart ollama openclaw-proxy"
sleep 10
ssh <hostname> "cd ~/openclaw && docker compose restart openclaw-gateway"
```

**Common cause:** The gateway health check probes `/api/health` every 30 seconds. If the agent subsystem crashes (not just the HTTP process), the container becomes unhealthy. A simple restart recovers it in all known cases — there is no persistent state that can be corrupted by a crash.
