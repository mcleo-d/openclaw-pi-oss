# Security Policy

## Scope

The following are in scope for security reports against this project:

- `config/etc/ollama-proxy/proxy.py` — the Ollama proxy, including its injection detection logic
- Configuration templates in `config/` — any template that, if followed, produces an insecure deployment
- Documentation in `docs/` — any guidance that is incorrect or that would lead a deployer to introduce a vulnerability
- The CI pipeline (`.github/workflows/`) — any misconfiguration that could allow secrets to be leaked

The following are **out of scope** for this project. Please report these to the relevant upstream project instead:

- OpenClaw itself — report via the [OpenClaw project](https://openclaw.ai)
- Ollama — report via the [Ollama repository](https://github.com/ollama/ollama)
- Telegram, Signal, or any other messaging platform

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting to disclose security issues:

**[Report a vulnerability](https://github.com/mcleo-d/openclaw-pi-oss/security/advisories/new)**

Do not open a public GitHub issue for security vulnerabilities. Private reporting keeps the
disclosure confidential until a fix is available.

When reporting, please include:

- A clear description of the vulnerability and its potential impact
- Steps to reproduce, including hardware, OS, and software versions where relevant
- Any suggested mitigations if you have them

## Response

- Acknowledgement within **7 days** of submission
- A resolution or documented mitigation plan within **30 days** where possible
- Credit to the reporter in the advisory unless anonymity is requested

## Supported versions

This project does not publish versioned releases. Security fixes are applied to the `main`
branch. Deployers are responsible for keeping their local deployments current.
