# AGENTS.md — AI Contribution Guide

This file provides context for AI coding assistants (Claude Code, GitHub Copilot, Cursor,
or any other tool) contributing to `openclaw-pi-oss`.

---

## What this project is

`openclaw-pi-oss` is a **reference deployment**, not a runnable application. It contains:

- Sanitised configuration templates for deploying OpenClaw on a Raspberry Pi 5
- Documentation covering architecture, security rationale, and deployment steps
- A custom Ollama proxy (`config/etc/ollama-proxy/proxy.py`) with all values externalised

There is no local development mode. The stack requires a Raspberry Pi running Ollama natively.
Do not attempt to generate a local dev environment, Docker Compose override, or test harness —
none of these are in scope for this project.

---

## Absolute invariants — never violate these

### Never commit

- `patterns.conf` — injection detection signatures; excluded by `.gitignore`; must be created
  on the target system by the operator
- `classifier-prompt.txt` — Gate 2 classifier system prompt; excluded by `.gitignore`; must be
  created on the target system by the operator
- `.env` — credentials and tokens; excluded by `.gitignore`
- `openclaw.json` — live provider config; excluded by `.gitignore`
- Real hostnames, IP addresses, usernames, or port numbers specific to any live system
- Numeric values for security thresholds (SSH `Max*`, fail2ban `bantime`/`findtime`/`maxretry`)

### proxy.py contract

- All tunable constants must use `os.environ.get("PROXY_*", "<default>")` — never hardcode
- `PROXY_LISTEN_PORT` intentionally has no default; the proxy exits if it is unset
- Injection patterns must never be added to `proxy.py` — they belong in `patterns.conf` only
- If adding a new tunable, use the `PROXY_` prefix, add an `Environment=` placeholder to
  `config/etc/systemd/system/ollama-proxy.service`, and document it in
  `docs/04-docker-openclaw.md`

### Template convention

- Files named `*.template` must never contain real values — only `<your-value>` placeholders
- Non-template files in `config/etc/` and `config/home/` that are complete as-is (e.g.,
  `daemon.json`, `sysctl.d/99-hardening.conf`) must not have `<your-value>` placeholders added
- Files with `<your-value>` placeholders that require operator input before deployment (e.g.,
  `ollama-proxy.service`, `sshd_config.d/99-hardening.conf`) are intentional — do not fill
  them in

### patterns.conf and classifier-prompt.txt contract

- Neither file is in the repository and must not be added
- The proxy refuses to start if either file is missing, unreadable, or empty
- Documentation may describe the *categories* of patterns without listing specific signatures
- Documentation must not reproduce the classifier system prompt text

---

## Adding a new configuration file

1. Place it under `config/etc/` or `config/home/` mirroring the target filesystem path
2. Add an entry to the file map in `config/README.md` (path, permissions, notes)
3. If the file contains or may contain sensitive values, add it to `.gitignore` and provide
   a `*.template` version instead
4. Use `<your-value>` for any site-specific placeholder — never invent example values

---

## Security philosophy

This project applies defence in depth. Every layer assumes the layers above it may be
compromised. When making changes:

- Do not weaken any existing security control without explicit justification
- Document the rationale for any new control in the relevant section of
  `docs/03-security-hardening.md`
- Changes to the Docker configuration must preserve: `cap_drop: ALL`, `read_only: true`,
  `no-new-privileges: true`, and resource limits

---

## CI pipeline

This project has a narrow CI pipeline scoped to the reference deployment's content. There is no deployment pipeline and none is planned.

If a CI pipeline is ever added, the appropriate scope is narrow:

| Stage | Tool | Purpose |
|---|---|---|
| Secrets scan | `detect-secrets` | Verify baseline has no new violations |
| Markdown lint | `markdownlint-cli` | Catch formatting issues in docs |
| Python syntax | `python3 -m py_compile` | Catch syntax errors in `proxy.py` |
| Proxy tests | `pytest` | Run unit tests if test suite exists |

Do not add container image scanning, SBOM generation, ECR push, ECS deployment, or cloud authentication stages — there are no cloud resources to target.

---

## Agent team

This project uses a team of 18 specialist agents defined in `.claude/agents/`. Not all agents
are relevant to this project. Invoking an inapplicable agent will produce plausible-looking
but incorrect output — it will apply cloud, frontend, or platform engineering expertise to a
project that has none of those concerns.

### Applicable agents — use these

| Agent | When to use |
|---|---|
| `python-developer` | Any change to `proxy.py` or future Python tooling |
| `linux-systems-engineer` | systemd units, kernel sysctl, SSH, UFW, fail2ban, apt, boot config, Docker daemon |
| `ai-ml-engineer` | Model selection, Ollama tuning, quantisation, inference performance, injection detection design research |
| `security-engineer` | All security control design, threat modelling, injection detection architecture, hardening review |
| `code-reviewer` | Reviewing any PR — proxy code, configuration templates, or documentation |
| `systematic-debugger` | Diagnosing proxy failures, systemd service failures, or unexpected Ollama behaviour |
| `deploy-checklist` | Before deploying any change to the Pi — use the Pi/edge deployment section |
| `qa-engineer` | Proxy test suite design, pytest coverage, fail-open verification |

### Partially applicable agents — use with narrowed scope

| Agent | Applicable scope | Do not use for |
|---|---|---|
| `systems-architect` | ADRs for roadmap decisions (AppArmor, reverse proxy, Signal integration); proxy architecture | AWS, ECS, CouchDB, service mesh |
| `devops-engineer` | `daemon.json` review; lightweight CI workflow if ever added | Full cloud pipeline, ECR, ECS, ArgoCD |
| `business-analyst` | User stories and acceptance criteria for roadmap items | Cloud product backlogs |
| `scrum-master` | Backlog management and sprint process for roadmap work | Cloud delivery ceremonies |

### Inapplicable agents — do not use on this project

| Agent | Why inapplicable |
|---|---|
| `backend-developer` | Node.js/TypeScript/Go backend services — no backend service is being built here |
| `frontend-developer` | React/Next.js UI — no frontend in scope; OpenClaw UI is upstream and unmodified |
| `fullstack-developer` | Spans Node.js + React — neither applies to this project |
| `platform-engineer` | Backstage, ArgoCD, Kong, Linkerd — no platform infrastructure in scope |
| `sre-engineer` | Prometheus, Grafana, SLOs, error budgets — no cloud observability in scope |
| `ui-designer` | Design tokens, Tailwind, component specs — no UI in scope |

---

## What a good AI-assisted contribution looks like

- Config changes: uses `<your-value>` or `${ENV_VAR}` for all site-specific values
- Proxy changes: new behaviour via `os.environ.get("PROXY_NEW_VAR", "default")`
- Documentation: accurate, no real values, relative links between docs
- New config file: entry in `config/README.md` file map, `.gitignore` entry if sensitive

## Before marking a contribution complete, verify

- No real values appear in any file
- No patterns were added to `proxy.py`
- `config/README.md` file map is updated if files were added or removed
- `.gitignore` is updated if a new sensitive file was introduced
- The `detect-secrets` baseline passes: `detect-secrets scan --baseline .secrets.baseline`
