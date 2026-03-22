# OpenClaw on Raspberry Pi 5

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/mcleo-d/openclaw-pi-oss/actions/workflows/ci.yml/badge.svg)](https://github.com/mcleo-d/openclaw-pi-oss/actions/workflows/ci.yml)

A hardened, zero-trust reference deployment of [OpenClaw](https://openclaw.ai) — a
self-hosted, open-source AI agent gateway — on a Raspberry Pi 5. This project provides
sanitised configuration templates, security hardening documentation, and a custom Ollama
proxy that manages context window size, suppresses thinking-mode overhead, truncates
oversized system prompts, and caps conversation history to keep inference fast on
constrained hardware.

---

## Who is this for?

- Homelab and edge AI enthusiasts running self-hosted AI agents on low-cost hardware
- Security-minded developers exploring AI agent threat models and defence in depth
- Anyone deploying OpenClaw on ARM hardware who wants a hardened starting point

---

## Architecture

```text
Your Phone (Telegram / Signal)
        │
        ▼
  [Messaging Platform]
        │
        ▼
  OpenClaw Gateway          ← Docker container (hardened, localhost-only)
  <hostname>.local:18789        ← Raspberry Pi 5, 8GB RAM
        │
        ▼
  openclaw-proxy            ← Systemd service
  <your-proxy-port>             caps num_ctx, injects think=false,
                                truncates system prompt, caps history
        │
        ▼
  Ollama (local LLM)        ← Native systemd service, loopback-only
  127.0.0.1:11434               qwen3:1.7b-q4_K_M (primary)
                                qwen2.5:3b-instruct-q4_K_M (fallback)
```

An enhanced variant (`ollama-proxy`) is also available with two-layer prompt injection
detection for operators who need it. See [`docs/04-docker-openclaw.md`](docs/04-docker-openclaw.md).

---

## Hardware requirements

| Component | Requirement |
|---|---|
| Hardware | Raspberry Pi 5 (8GB RAM recommended) |
| OS | Raspberry Pi OS Lite 64-bit (Bookworm / Debian 12) |
| Python | 3.9 or later (for the Ollama proxy) |
| Storage | 16GB+ microSD or SSD |
| Network | Ethernet recommended for stability |

The Pi 5 (8GB) is the tested configuration. Lower RAM may work but leaves less headroom
for the LLM KV cache and the OpenClaw container running concurrently.

---

## The Ollama proxy

The core custom component in this project is
[`config/etc/openclaw-proxy/proxy.py`](config/etc/openclaw-proxy/proxy.py) — a lightweight
Python HTTP proxy that sits between OpenClaw and Ollama.

On Pi 5 hardware, OpenClaw's default behaviour causes problems that cannot be fixed in
OpenClaw's own configuration:

| Problem | Proxy fix |
|---|---|
| OpenClaw sends `num_ctx=16384` → 1.8 GiB KV cache → inference hangs | Cap `num_ctx` at `PROXY_MAX_CTX` (4096) |
| qwen3 thinking mode generates 200+ tokens per tool call (~50s/call) | Inject `think: false` on every request |
| OpenClaw sends a ~4,600-token system prompt → ~248s prefill on Pi 5 | Truncate system message to `PROXY_MAX_SYSTEM_CHARS` |
| Conversation history grows unboundedly → increasing prefill over time | Cap history to `PROXY_MAX_MESSAGES` (4 non-system messages) |

All tunable values are environment variables set in `openclaw-proxy.service`. An enhanced
variant (`ollama-proxy`) is also provided for operators who require two-layer prompt
injection detection; see [`docs/04-docker-openclaw.md`](docs/04-docker-openclaw.md) for both variants.

---

## Security model

This project applies a zero-trust, defence-in-depth model across seven layers:

| Layer | Control |
|---|---|
| 1 | SSH hardening — key-only auth, no root login, session timeouts |
| 2 | UFW firewall — deny all inbound except SSH; proxy port restricted to container bridge |
| 3 | fail2ban — brute-force protection on SSH |
| 4 | Kernel hardening — sysctl: ASLR, SYN cookies, ICMP redirect blocking, martian logging |
| 5 | Disabled services — bluetooth, ModemManager, triggerhappy removed |
| 6 | Docker daemon hardening — ICC disabled, no-new-privileges, resource limits |
| 7 | Container hardening — cap_drop ALL, read-only rootfs, tmpfs, memory/CPU/PID limits |

See [`docs/03-security-hardening.md`](docs/03-security-hardening.md) for the full rationale
behind each control.

---

## Project status

| Component | Status |
|---|---|
| Raspberry Pi 5 OS setup | Complete |
| OS security hardening | Complete |
| Docker Engine installation | Complete |
| Ollama installed (native) | Complete — v0.17.0, bound to `127.0.0.1:11434` |
| Models pulled | Complete — `qwen3:1.7b-q4_K_M` (primary), `qwen2.5:3b-instruct-q4_K_M` (fallback) |
| Models benchmarked and selected | Complete — see [`docs/05-ollama-model-research.md`](docs/05-ollama-model-research.md) |
| Ollama proxy deployed | Complete — context cap, think=false, system truncation, history capping |
| OpenClaw running | Complete — gateway healthy, UI accessible |
| Telegram integration | Complete — owner-only via pairing policy |
| Signal integration | Under investigation — see [ROADMAP.md](ROADMAP.md) |
| AppArmor profile | Planned — see [ROADMAP.md](ROADMAP.md) |

---

## Quick start

See [`config/README.md`](config/README.md) for the full deployment guide, including:

- File placement and permissions
- Template placeholder substitution
- Boot configuration changes required for Docker memory limiting
- UFW firewall rules
- Service startup sequence

For day-to-day operation and troubleshooting, see
[`docs/04-docker-openclaw.md`](docs/04-docker-openclaw.md).

---

## Documentation

| Document | Description |
|---|---|
| [`config/README.md`](config/README.md) | Deployment guide — file map, permissions, step-by-step |
| [`docs/01-hardware.md`](docs/01-hardware.md) | Hardware and connectivity reference |
| [`docs/02-os-and-updates.md`](docs/02-os-and-updates.md) | OS setup and update process |
| [`docs/03-security-hardening.md`](docs/03-security-hardening.md) | Security hardening — all seven layers |
| [`docs/04-docker-openclaw.md`](docs/04-docker-openclaw.md) | Docker and OpenClaw setup, proxy config, troubleshooting |
| [`docs/05-ollama-model-research.md`](docs/05-ollama-model-research.md) | Model benchmarks, selection rationale, Pi 5 performance data |
| [`ROADMAP.md`](ROADMAP.md) | Planned improvements and future work |
| [`CHANGELOG.md`](CHANGELOG.md) | Change history — breaking changes, new features, fixes |
| [`GOVERNANCE.md`](GOVERNANCE.md) | Project decision-making and maintainer path |
| [`SUPPORT.md`](SUPPORT.md) | How to get help and which channel to use |
| [`NOTICE`](NOTICE) | Third-party attribution (Apache 2.0 requirement) |

---

## Contributing

Contributions are welcome — not just code. Hardware testing on different Pi variants, model
benchmarks, documentation improvements, and security feedback are all valuable.

See [CONTRIBUTING.md](CONTRIBUTING.md) to get started and [AGENTS.md](AGENTS.md) for
guidance on AI-assisted contributions.

---

## Licence

Apache 2.0 — see [LICENSE](LICENSE).

## Maintainer

[James McLeod](https://github.com/mcleo-d)
