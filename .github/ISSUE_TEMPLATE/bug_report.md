---
name: Bug report
about: Something is not working as documented
labels: bug
---

## Environment

| Item | Value |
|---|---|
| Pi model and RAM | e.g. Raspberry Pi 5, 8GB |
| OS and kernel | e.g. Raspberry Pi OS Lite 64-bit, kernel 6.12.62 |
| Ollama version | e.g. v0.17.0 |
| Python version | e.g. 3.11.2 |
| Component | proxy / Docker config / SSH hardening / other |

## What happened

<!-- Describe what went wrong. -->

## Steps to reproduce

1.
2.
3.

## Expected behaviour

<!-- What should have happened? -->

## Logs

<!-- Paste relevant logs below. Remove any sensitive values before posting. -->

**Proxy logs:**

```text
sudo journalctl -u ollama-proxy -n 50 --no-pager
```

**OpenClaw logs:**

```text
docker compose -f ~/openclaw/docker-compose.yml logs --tail=50 openclaw-gateway
```
