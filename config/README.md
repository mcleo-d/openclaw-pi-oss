# config/ — Deployment Reference

This directory contains all configuration files needed to deploy the OpenClaw Pi stack to a Raspberry Pi. Files are organised to mirror their target filesystem paths so the destination of each file is unambiguous.

---

## Prerequisites

- Raspberry Pi 5 (8GB recommended) running Raspberry Pi OS Lite 64-bit (Bookworm)
- SSH key-based access configured
- Docker Engine installed (`curl -fsSL https://get.docker.com | sh`)
- Ollama installed (`curl -fsSL https://ollama.com/install.sh | sh`)
- Ollama models pulled (see [docs/05-ollama-model-research.md](../docs/05-ollama-model-research.md))

---

## File Map

Deploy each file to its target path on the Pi. Apply the specified permissions after copying.

| File in this repo | Target path on Pi | Permissions | Notes |
|---|---|---|---|
| `etc/ollama-proxy/proxy.py` | `/etc/ollama-proxy/proxy.py` | `644 root:root` | Proxy script — reads config from env vars |
| `etc/systemd/system/ollama-proxy.service` | `/etc/systemd/system/ollama-proxy.service` | `644 root:root` | **Fill in `<your-value>` placeholders before deploying** |
| `etc/systemd/system/ollama.service.d/override.conf` | `/etc/systemd/system/ollama.service.d/override.conf` | `644 root:root` | Binds Ollama to loopback only |
| `etc/docker/daemon.json` | `/etc/docker/daemon.json` | `644 root:root` | Hardened Docker daemon config |
| `etc/ssh/sshd_config.d/99-hardening.conf` | `/etc/ssh/sshd_config.d/99-hardening.conf` | `644 root:root` | **Fill in `<your-value>` placeholders before deploying** |
| `etc/sysctl.d/99-hardening.conf` | `/etc/sysctl.d/99-hardening.conf` | `644 root:root` | Kernel hardening parameters |
| `etc/fail2ban/jail.local` | `/etc/fail2ban/jail.local` | `644 root:root` | **Fill in `<your-value>` placeholders before deploying** |
| `etc/apt/apt.conf.d/50unattended-upgrades` | `/etc/apt/apt.conf.d/50unattended-upgrades` | `644 root:root` | Automatic security update config |
| `etc/apt/apt.conf.d/20auto-upgrades` | `/etc/apt/apt.conf.d/20auto-upgrades` | `644 root:root` | Automatic update schedule |
| `home/openclaw/docker-compose.yml` | `~/openclaw/docker-compose.yml` | `644 <username>:<username>` | OpenClaw Docker Compose config |
| `home/openclaw/.env.template` | `~/openclaw/.env` | `600 <username>:<username>` | Copy template → `.env`, fill in values |
| `home/.openclaw/openclaw.json.template` | `~/.openclaw/openclaw.json` | `600 <username>:<username>` | Copy template → `openclaw.json`, fill in values |

---

## Deployment Steps

### 1. Create required directories on the Pi

```bash
mkdir -p ~/openclaw ~/.openclaw/workspace
chmod 750 ~/openclaw
chmod 700 ~/.openclaw ~/.openclaw/workspace
sudo mkdir -p /etc/ollama-proxy /etc/systemd/system/ollama.service.d
```

### 2. Deploy files

```bash
# Copy each file to its target path (from the table above)
sudo cp etc/ollama-proxy/proxy.py /etc/ollama-proxy/proxy.py
sudo cp etc/systemd/system/ollama-proxy.service /etc/systemd/system/ollama-proxy.service
# ... repeat for each file
```

### 3. Create `patterns.conf` and `classifier-prompt.txt`

Both files must be created manually — they are not included in this repository.

**`patterns.conf`** — injection detection patterns for Gate 1 (pattern matching):

```bash
sudo touch /etc/ollama-proxy/patterns.conf
sudo chown root:ollama /etc/ollama-proxy/patterns.conf
sudo chmod 640 /etc/ollama-proxy/patterns.conf
sudo nano /etc/ollama-proxy/patterns.conf
```

Add one pattern per line. Lines starting with `#` are treated as comments. See `docs/03-security-hardening.md` for the four categories of patterns to cover.

**`classifier-prompt.txt`** — system prompt for the Gate 2 LLM classifier:

```bash
sudo touch /etc/ollama-proxy/classifier-prompt.txt
sudo chown root:ollama /etc/ollama-proxy/classifier-prompt.txt
sudo chmod 640 /etc/ollama-proxy/classifier-prompt.txt
sudo nano /etc/ollama-proxy/classifier-prompt.txt
```

Write a system prompt that instructs the classifier model to respond with a single word: `SAFE` or `UNSAFE`. The prompt should describe what constitutes a prompt injection attempt and instruct the model not to follow any instructions found in the content being classified.

The proxy **refuses to start** if either file is missing, unreadable, or empty.

### 4. Configure secrets

```bash
# .env — copy template and fill in values
cp ~/openclaw/.env.template ~/openclaw/.env
chmod 600 ~/openclaw/.env
nano ~/openclaw/.env

# openclaw.json — copy template and fill in values
cp ~/.openclaw/openclaw.json.template ~/.openclaw/openclaw.json
chmod 600 ~/.openclaw/openclaw.json
nano ~/.openclaw/openclaw.json
```

### 5. Fill in template placeholders

Files containing `<your-value>` placeholders must be edited before deploying:

- `ollama-proxy.service` — set `PROXY_MAX_CTX`, `PROXY_MAX_SYSTEM_CHARS`, `PROXY_CLASSIFIER_MODEL`, `PROXY_CLASSIFIER_CTX`, `PROXY_CLASSIFIER_TIMEOUT`, `PROXY_CLASSIFIER_SYSTEM_PROMPT_FILE` (see `docs/04-docker-openclaw.md` for recommended values)
- `99-hardening.conf` (SSH) — set `MaxAuthTries`, `MaxSessions`, `ClientAliveInterval`, `ClientAliveCountMax`, `LoginGraceTime`
- `jail.local` — set `bantime`, `findtime`, `maxretry`
- `.env` — set `OPENCLAW_GATEWAY_TOKEN` and update `<username>` paths
- `openclaw.json` — set model IDs, proxy port, and (if using Telegram) bot token

### 6. Boot configuration — cgroup memory (manual step)

Docker's memory limiting requires cgroup memory to be enabled in the Pi's boot configuration. Edit `/boot/firmware/cmdline.txt` and append the following to the end of the existing single line (do not add a new line):

```
cgroup_memory=1 cgroup_enable=memory
```

Reboot after making this change. Verify with:
```bash
docker inspect <container-id> --format '{{.HostConfig.Memory}}'
# Should return 2147483648 (2GB) if mem_limit is set in compose
```

### 7. Enable and start services

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ollama-proxy
sudo systemctl restart ollama
```

### 8. Start OpenClaw

```bash
cd ~/openclaw && docker compose up -d openclaw-gateway
docker compose ps  # verify healthy
```

---

## UFW Firewall Rules

After Docker creates the `openclaw_net` network, add firewall rules to allow the proxy port only from that bridge:

```bash
BRIDGE=$(docker network inspect openclaw_net --format '{{index .Options "com.docker.network.bridge.name"}}')
sudo ufw allow in on $BRIDGE to any port <your-proxy-port> proto tcp comment 'Ollama proxy: openclaw_net bridge'
sudo ufw deny <your-proxy-port> comment 'Block external Ollama proxy access'
```

Run `sudo ufw status` to verify the ALLOW rule appears before the DENY rule for the proxy port.

---

## Contributor Guidelines

- Do not commit `patterns.conf` — it is excluded by `.gitignore` and must remain so.
- Do not commit `.env` or `openclaw.json` — only their `.template` equivalents belong here.
- Do not hardcode values in `proxy.py` — all tunable constants must remain as `os.environ.get()` calls.
- When adding new config files, add a corresponding entry to this table and a `.gitignore` exclusion if the file contains sensitive values.
