# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project does not use semantic versioning — entries are dated. See
[SECURITY.md](SECURITY.md) for the breaking-change deprecation policy.

---

## [Unreleased]

---

## [2026-03-22]

### Added

- `openclaw-proxy` (minimal variant): system message truncation
  (`PROXY_MAX_SYSTEM_CHARS`) and conversation history capping (`PROXY_MAX_MESSAGES`)

### Fixed

- `openclaw-proxy`: `PROXY_MAX_MESSAGES=0` now correctly clears all non-system
  history instead of being treated as unlimited
- README variant table and model name updated to match current deployment

---

## [2026-03-21]

### Added

- `openclaw-proxy` — new minimal proxy variant: `think:false` injection and
  `num_ctx` capping with no injection detection, for home-lab use cases where
  operator-controlled input makes Gate 1/2 detection unnecessary. All config via
  `PROXY_*` env vars; no external files required.
- Unit tests covering the minimal proxy variant
- Deployment documentation for the minimal variant in `docs/04-docker-openclaw.md`

### Fixed

- `openclaw-proxy`: `think: false` injection was placed after body reserialisation;
  moved to correct position so it is always forwarded to Ollama

### Changed

- Model stability addendum: `qwen3:1.7b-q4_K_M` confirmed stable in production on
  Pi 5 as of 2026-03-21 (added to `docs/05-ollama-model-research.md`)

---

## [2026-03-08] — Initial publication

### Added

- `ollama-proxy` (enhanced variant): `think:false` injection, `num_ctx` cap,
  system message truncation, Gate 1 pattern-matching injection detection,
  Gate 2 LLM-classifier injection detection
- Systemd service files for both Ollama and the proxy
- Security hardening documentation across eight layers: SSH, UFW, fail2ban,
  sysctl, disabled services, Docker daemon, container hardening, prompt injection
- Sanitised configuration templates for all system components
- Docker Compose configuration for OpenClaw with full container hardening
  (`cap_drop: ALL`, `read_only: true`, `no-new-privileges`, resource limits)
- Model research documentation: benchmarks, selection rationale, Pi 5 performance
  data for `qwen3:1.7b-q4_K_M` and `qwen2.5:3b-instruct-q4_K_M`
- Deployment guide (`config/README.md`) with file map, permissions, and
  step-by-step setup sequence
- CI pipeline: secrets scan (`detect-secrets`), placeholder check, markdown lint
  (`markdownlint-cli2`), proxy syntax check (`py_compile`)
- Dependabot configuration tracking GitHub Actions SHAs and `detect-secrets` version
- Local pre-commit hook mirroring all CI checks
- CI test guide documenting every enforced rule with annotated examples
- GitHub issue templates: bug report, feature request, config question
- Pull request template enforcing project invariants

### Changed

- `actions/checkout` pinned to commit SHA `6.0.2`
- `DavidAnson/markdownlint-cli2-action` pinned to commit SHA `v22`
