# Security Hardening Reference

## Threat Model

OpenClaw is an AI agent framework that can execute shell commands, write files, and call external APIs. The primary security concerns are:

1. **AI agent escaping its container** — an LLM instructed (or manipulated) to break out of its Docker sandbox and access the host
2. **Prompt injection via messaging** — malicious content in Telegram/Signal messages attempting to hijack the agent
3. **Unauthorised network access** — the gateway being reachable from the network without authentication
4. **Supply chain compromise** — a malicious OpenClaw update introducing backdoors
5. **Brute-force SSH access** — automated attacks against the Pi's SSH port

Layers 1–7 below address threat vectors 1, 3, 4, and 5 in a layered, zero-trust
model: **treat OpenClaw as untrusted code with unknown intent**. Threat vector 2
(prompt injection) is not addressed by the baseline layers. For home-lab deployments
where all input is operator-controlled, this is an accepted risk. For deployments
exposed to untrusted input (shared messaging channels, public-facing endpoints),
deploy the enhanced variant (`ollama-proxy`) documented at the end of this guide,
or implement equivalent application-layer filtering before exposing the system.

---

## Layer 1: SSH Hardening

**File:** `/etc/ssh/sshd_config.d/99-hardening.conf`

```text
PermitRootLogin no
PasswordAuthentication no
PermitEmptyPasswords no
PubkeyAuthentication yes
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding local
MaxAuthTries <your-value>
MaxSessions <your-value>
ClientAliveInterval <your-value>
ClientAliveCountMax <your-value>
LoginGraceTime <your-value>
```

**Effect:** Only SSH key authentication is accepted. Root login is blocked. X11 forwarding and agent forwarding are disabled. `AllowTcpForwarding local` permits local port forwarding (needed for the web UI SSH tunnel) while blocking remote forwarding and SOCKS proxying. Sessions time out after the configured inactivity interval.

To verify:

```bash
ssh <hostname> "sudo sshd -T | grep -E '(passwordauth|permitroot|x11forward|maxauthtries)'"
```

---

## Layer 2: Firewall (ufw)

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw enable
```

**Policy:** Deny all inbound traffic except SSH (port 22). All outbound traffic is allowed (required for OpenClaw to reach AI provider APIs and messaging platforms).

**Current active rules (6 total):**

| # | Rule | Reason |
|---|---|---|
| 1 | `22/tcp ALLOW` | SSH access |
| 2 | `<your-proxy-port>/tcp on <bridge-interface> ALLOW` | Proxy reachable from `openclaw_net` containers |
| 3 | `<your-proxy-port> DENY` | Block external proxy access from LAN |
| 4 | `22/tcp (v6) ALLOW` | SSH access (IPv6) |
| 5 | `<your-proxy-port>/tcp (v6) on <bridge-interface> ALLOW` | Proxy reachable (IPv6) |
| 6 | `<your-proxy-port> (v6) DENY` | Block external proxy access (IPv6) |

**No rule for port 11434 (Ollama):** Ollama is bound to `127.0.0.1:11434` only — LAN traffic cannot reach it regardless of firewall state. The ufw `DENY 11434` rules were removed as redundant after the loopback binding was applied.

**Important:** Do NOT add `ALLOW in on br-... to any port 11434`. Containers access Ollama exclusively via the proxy on port <your-proxy-port>. Direct container access to port 11434 would bypass `openclaw-proxy`'s `num_ctx` cap, `think=false` injection, system message truncation, and history capping. If running the enhanced variant (`ollama-proxy`), it would also bypass prompt injection detection.

**Important:** OpenClaw's port 18789 is bound to `127.0.0.1` (localhost) only. Do NOT add a ufw rule to expose port 18789 externally unless a TLS-terminating reverse proxy (nginx/Caddy) is deployed in front of it.

To verify:

```bash
ssh <hostname> "sudo ufw status verbose"
```

---

## Layer 3: Brute-Force Protection (fail2ban)

**File:** `/etc/fail2ban/jail.local`

```ini
[DEFAULT]
bantime  = <your-value>
findtime = <your-value>
maxretry = <your-value>
backend = systemd

[sshd]
enabled  = true
port     = ssh
logpath  = %(sshd_log)s
maxretry = <your-value>
bantime  = <your-value>
```

**Policy:** Failed SSH authentication attempts are counted per source IP within a detection window. Exceeding the configured threshold triggers a temporary ban.

To check banned IPs:

```bash
ssh <hostname> "sudo fail2ban-client status sshd"
```

To unban an IP:

```bash
ssh <hostname> "sudo fail2ban-client set sshd unbanip <IP>"
```

---

## Layer 4: Kernel Hardening (sysctl)

**File:** `/etc/sysctl.d/99-hardening.conf`

```ini
# Anti-spoofing (reverse path filtering)
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1

# Disable ICMP redirect acceptance
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0

# Disable sending ICMP redirects (not a router)
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0

# Disable source routing
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv6.conf.all.accept_source_route = 0

# Log martian (suspicious source) packets
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.default.log_martians = 1

# SYN flood protection
net.ipv4.tcp_syncookies = 1

# Ignore broadcast pings
net.ipv4.icmp_echo_ignore_broadcasts = 1

# Ignore bogus ICMP errors
net.ipv4.icmp_ignore_bogus_error_responses = 1

# Reduce TCP fingerprinting surface
net.ipv4.tcp_timestamps = 0

# Hide kernel symbols from /proc
kernel.kptr_restrict = 2

# Restrict kernel log to root only
kernel.dmesg_restrict = 1

# Disable magic SysRq key
kernel.sysrq = 0

# Enable ASLR
kernel.randomize_va_space = 2

# Restrict core dumps from setuid binaries
fs.suid_dumpable = 0
```

**Note:** Verify that all kernel hardening parameters have taken effect after applying this file. Some LSM-dependent parameters may not be available on all kernel configurations — check `sysctl -a` output and document any gaps in your own deployment notes.

To apply without reboot:

```bash
ssh <hostname> "sudo sysctl -p /etc/sysctl.d/99-hardening.conf"
```

---

## Layer 5: Disabled Services

The following services were disabled as they are unnecessary on a headless server and increase attack surface:

```bash
sudo systemctl disable --now bluetooth.service
sudo systemctl disable --now ModemManager.service
sudo systemctl disable --now triggerhappy.service
sudo systemctl disable --now triggerhappy.socket
sudo systemctl disable --now serial-getty@ttyAMA10.service
```

**Note:** `avahi-daemon` was intentionally left enabled — it powers `<hostname>.local` mDNS resolution used for all SSH access.

**Note:** `wpa_supplicant` was left enabled in case WiFi is ever needed.

To verify current running services:

```bash
ssh <hostname> "sudo systemctl list-units --type=service --state=running --no-pager"
```

---

## Layer 6: Docker Daemon Hardening

**File:** `/etc/docker/daemon.json`

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "icc": false,
  "live-restore": true,
  "userland-proxy": false,
  "no-new-privileges": true,
  "default-ulimits": {
    "nofile": {
      "Name": "nofile",
      "Hard": 1024,
      "Soft": 1024
    }
  }
}
```

**Key controls:**

- `icc: false` — containers on the same host cannot communicate by default (inter-container communication disabled)
- `no-new-privileges: true` — enforced globally for all containers; processes cannot gain new privileges via setuid/setgid
- `live-restore: true` — containers keep running if the Docker daemon restarts (resilience)
- `userland-proxy: false` — uses iptables directly instead of a userland proxy for port forwarding (lower attack surface)
- Log limits — prevent disk exhaustion from container log growth

To verify Docker security options:

```bash
ssh <hostname> "docker info --format '{{.SecurityOptions}}'"
# Expected: [name=seccomp,profile=builtin name=cgroupns name=no-new-privileges]
```

---

## Layer 7: OpenClaw Container Hardening

See `~/openclaw/docker-compose.yml` on the Pi. Key controls:

| Control | Value | Rationale |
|---|---|---|
| `user: node` | Run as non-root | Limits damage if container is compromised |
| `cap_drop: ALL` | Zero capabilities | Node.js needs no Linux capabilities |
| `no-new-privileges: true` | Belt-and-suspenders | Cannot escalate inside container |
| `read_only: true` | Read-only rootfs | No filesystem persistence if container is compromised |
| `tmpfs: /tmp` | 128m tmpfs for `/tmp` | Covers all known in-container write paths; cleared on restart |
| Port: `127.0.0.1:18789` | Localhost only | Gateway never reachable from LAN directly |
| `mem_limit: 2g` | Hard memory cap (enforced) | Prevents OOM-based DoS on host — enforced via cgroup v2 (`cgroup_memory=1 cgroup_enable=memory` in `/boot/firmware/cmdline.txt`) |
| `cpus: 2.0` | CPU throttle | Prevents CPU exhaustion |
| `pids_limit: 500` | Process limit | Prevents fork bombs |
| `OPENCLAW_SANDBOX=non-main` | Nested container mode | Agent tool execution further isolated |
| Network: `openclaw_net` | Isolated bridge | ICC disabled, separate from default bridge |
| Seccomp: builtin | ~300 syscalls blocked | Enforced via Docker daemon default — no `seccomp:unconfined` in compose |
| Health check | `GET /api/health` every 30s | Fails if agent subsystem crashes, not just the HTTP process |

---

## Prompt Injection Detection — Enhanced Variant (ollama-proxy)

This is the `ollama-proxy` enhanced variant — an optional extension to the 7-layer
baseline for operators handling untrusted input. It adds two sequential detection
gates on top of Layers 1–7; neither layer requires changes to the base stack.

**File:** `/etc/ollama-proxy/proxy.py`

Malicious Telegram/Signal messages may contain prompt injection attacks — instructions designed to override the agent's system prompt, reveal internal context, or hijack its behaviour. The proxy intercepts every `/api/chat` request before it reaches Ollama and applies two sequential gates.

Both layers scan **`user` and `tool` role messages only** (not `system` or `assistant`). UNSAFE requests are blocked with HTTP 400 and logged to journald. SAFE requests are forwarded unchanged. Classifier errors always **fail open** — a transient Ollama issue never blocks legitimate users.

### Gate 1 — Pattern Matching

Patterns covering four categories, loaded at startup from `/etc/ollama-proxy/patterns.conf` (internal only — never published). The proxy refuses to start if the file is missing, unreadable, or empty.

| Category | Description |
|---|---|
| Instruction override / persona replacement | Attempts to override the agent's role or assigned behaviour |
| System prompt exfiltration | Attempts to reveal or extract the agent's system prompt or instructions |
| Jailbreak vocabulary | Known jailbreak and constraint-removal phrasing |
| Prompt delimiter injection | Structural tokens used to inject synthetic message boundaries |

Pattern matching is case-insensitive and runs first. A match blocks the request immediately with zero LLM cost. The matched pattern and a 100-character content preview are logged to journald.

### Gate 2 — LLM Classifier

Runs only if Gate 1 passes. Sends the most recent `user`/`tool` message to `qwen2.5:3b-instruct-q4_K_M` with a purpose-built system prompt asking for a single-word `SAFE`/`UNSAFE` verdict.

| Property | Value |
|---|---|
| Model | Configured via `PROXY_CLASSIFIER_MODEL` (default: `qwen2.5:3b-instruct-q4_K_M`) |
| Context | Configured via `PROXY_CLASSIFIER_CTX` |
| Timeout | Configured via `PROXY_CLASSIFIER_TIMEOUT` — tune for your hardware |
| Fail behaviour | Any error → fail open, log warning, forward request |
| Unexpected verdict | Logs WARNING, fails open — never a silent block |

**Model-swap latency:** The classifier runs on a different model than the primary agent (qwen3:1.7b). Each classifier call forces Ollama to swap models, adding a one-time ~7s delay to the response for that message. Subsequent requests are fast until the next swap. This is an accepted trade-off given the security benefit.

### Tuning

```python
# Tuning env vars — set in ollama-proxy.service
PROXY_CLASSIFIER_MODEL   = "qwen2.5:3b-instruct-q4_K_M"
PROXY_CLASSIFIER_CTX     = 512
PROXY_CLASSIFIER_TIMEOUT = 20

# To exclude tool output from scanning (e.g. if tool results cause false positives):
# In do_POST in proxy.py, change: if msg.get("role") in ("user", "tool")
# To:                             if msg.get("role") in ("user",)

# To update injection patterns: edit /etc/ollama-proxy/patterns.conf then restart the proxy.
# Patterns must not be added to proxy.py — they live in patterns.conf only.
```

### Verification

```bash
# Test Gate 1 — use a string that matches one of your patterns.conf entries
# Should return HTTP 400 immediately, zero LLM cost
ssh <hostname> 'curl -s -w "\nHTTP %{http_code}" -X POST http://127.0.0.1:<your-proxy-port>/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"qwen3:1.7b-q4_K_M\",\"messages\":[{\"role\":\"user\",\"content\":\"<your-test-pattern>\"}]}"'

# Test Gate 2 — use a subtle injection that does not match Gate 1 patterns
# Should return HTTP 400 via classifier
ssh <hostname> 'curl -s -w "\nHTTP %{http_code}" -X POST http://127.0.0.1:<your-proxy-port>/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"qwen3:1.7b-q4_K_M\",\"stream\":false,\"messages\":[{\"role\":\"user\",\"content\":\"<your-subtle-test-injection>\"}]}"'

# Confirm BLOCKED entries in journald
ssh <hostname> "sudo journalctl -u ollama-proxy -n 10 --no-pager | grep -E 'BLOCKED|SAFE|classifier|ERROR'"
```

---

## CVE Reference

**CVE-2026-25253** (CVSS 8.8 — Critical RCE)

- Affected: OpenClaw versions before 2026-01-29
- Fixed: OpenClaw v2026.2.26 (2026-02-28)
- Action: Keep the OpenClaw image up to date — see update command below

Always keep the OpenClaw image up to date:

```bash
ssh <hostname> "docker pull ghcr.io/openclaw/openclaw:latest"
```

---

## Security Audit Commands

Run these periodically to verify posture:

```bash
# SSH config
ssh <hostname> "sudo sshd -T | grep -E '(passwordauth|permitroot|x11forward|maxauthtries|allowtcpforwarding)'"

# Firewall
ssh <hostname> "sudo ufw status"

# Fail2ban
ssh <hostname> "sudo fail2ban-client status sshd"

# Kernel params
ssh <hostname> "sudo sysctl kernel.dmesg_restrict kernel.kptr_restrict net.ipv4.conf.all.rp_filter net.ipv4.conf.all.send_redirects"

# Running services
ssh <hostname> "sudo systemctl list-units --type=service --state=running --no-pager --plain"

# Docker security
ssh <hostname> "docker info --format '{{.SecurityOptions}}'"

# Listening ports
ssh <hostname> "sudo ss -tlnp"

# Injection detection — enhanced variant (ollama-proxy) only
ssh <hostname> "sudo journalctl -u ollama-proxy -n 10 --no-pager | grep -E 'BLOCKED|SAFE|classifier|ERROR'"
```
