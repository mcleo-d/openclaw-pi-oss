# Roadmap

Planned improvements and future work for `openclaw-pi-oss`. Contributions toward any of
these items are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for how to get involved,
and open an issue to discuss an approach before starting significant work.

---

## Signal Integration

**Goal:** Use Signal as a messaging interface alongside or instead of Telegram.

Signal is not natively supported by OpenClaw. OpenClaw's messaging integrations are built
around platforms with official bot APIs; Signal intentionally has no official bot API.

### Potential approaches

#### Option A — signal-cli bridge

[signal-cli](https://github.com/AsamK/signal-cli) is an unofficial Signal CLI client.
A REST API wrapper ([bbernhard/signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api))
can expose it as an HTTP API.

```text
Signal App → signal-cli-rest-api (Docker) → OpenClaw webhook
```

- Pros: works with an existing Signal account; messages are end-to-end encrypted
- Cons: violates Signal's Terms of Service; requires linking a phone number; unofficial and fragile
- Effort: high — requires building a custom OpenClaw plugin or webhook integration

#### Option B — Custom OpenClaw plugin

OpenClaw has a plugin/extension SDK. A custom plugin could listen to signal-cli events and
route them to the OpenClaw agent.

#### Option C — Wait for official support

Monitor the OpenClaw roadmap. Given Signal's stance on bots, native support is unlikely
in the near term.

---

## AppArmor Profile for the OpenClaw Container

**Goal:** Add mandatory access control (MAC) to the OpenClaw container, restricting what
file paths and syscalls the container process can access beyond Docker's default isolation.

### Current state

- AppArmor is available on Raspberry Pi OS
- Docker's default `docker-default` AppArmor profile applies
- No custom profile is active for the OpenClaw container

### Plan

1. Install `apparmor-utils` on the Pi
2. Generate a base profile from the running container using `aa-genprof`
3. Run OpenClaw in complain mode, observe denials, tune the profile
4. Switch to enforce mode
5. Reference the profile in `docker-compose.yml`:

   ```yaml
   security_opt:
     - apparmor:openclaw-profile
   ```

6. Add the profile to `config/` and document it in `docs/03-security-hardening.md`

---

## Reverse Proxy with TLS

**Goal:** Provide a reference configuration for exposing the OpenClaw gateway outside the
local network via a TLS-terminating reverse proxy, for deployers who need remote access.

**Current state:** Port 18789 is bound to localhost only. The firewall blocks all external
inbound traffic except SSH. This is the correct default.

### Recommended approach

- Use **Caddy** (automatic TLS via Let's Encrypt) or **nginx**
- Add authentication in front of the proxy (HTTP Basic Auth or an OAuth2 proxy)
- Add UFW rules for ports 80 and 443 only
- Document the security trade-offs clearly — external access meaningfully expands the
  attack surface

This item should not be pursued until the core stack (proxy, injection detection, container
hardening) is stable and well-documented.

---

## System Prompt Compression

**Goal:** Replace blunt character-count truncation of the system prompt with intelligent
extraction that preserves agent capability while keeping prefill latency acceptable.

**Constraint:** At ~16 t/s prefill rate on a Pi 5 Cortex-A76:

- 500 chars → ~8s first-turn latency (current truncation limit — acceptable)
- 2000 chars → ~30s first-turn latency (approaches UX limit for Telegram responses)

**Approach:** The OpenClaw system prompt is dominated by JSON tool-schema blocks. A
heuristic extractor that strips JSON-formatted tool definitions and retains
natural-language instruction paragraphs could recover significant agent capability at
the same latency cost. The natural-language instructions that shape agent behaviour are
a small fraction of the total prompt length.

**Caution:** Requires `security-engineer` review before deployment — a compression
function that accidentally strips safety instructions or tool-use constraints would be
a regression. Compression must be deterministic and auditable.

**Owner:** `ai-ml-engineer` (design + evaluation) + `python-developer` (implementation)
