# Contributing to openclaw-pi-oss

Thank you for your interest in contributing. This project welcomes contributions of all kinds —
not just code. Hardware testing, documentation improvements, model research, and security
feedback are all valuable.

---

## Ways to contribute

- **Hardware variants** — tested this stack on a Pi 4, CM5, or other ARM board? Document your
  findings and open a PR against the relevant docs
- **Model research** — benchmarked a different Ollama model on Pi hardware? Add results to
  `docs/05-ollama-model-research.md`
- **Security improvements** — identified a gap in the hardening or a stronger control? See
  `docs/03-security-hardening.md` and open a PR with rationale
- **Documentation** — clarifications, corrections, better explanations of the deployment steps
- **Proxy extensions** — new features for `proxy.py` (see constraints below)
- **Roadmap items** — picking up an item from `ROADMAP.md`

---

## Prerequisites

To test changes that affect the proxy or deployment configs, you need:

- Raspberry Pi 5 (8GB recommended) running Raspberry Pi OS Lite 64-bit (Bookworm)
- Python 3.9 or later (required for `proxy.py` — uses `tuple[T, U]` type annotations)
- Docker Engine and Ollama installed on the Pi
- At least one Ollama model pulled (`qwen3:1.7b-q4_K_M` recommended)

Documentation-only changes do not require Pi hardware.

---

## What belongs in this repository

- Generic, parameterised configuration templates with `<your-value>` placeholders
- Documentation covering architecture, security rationale, and deployment
- `proxy.py` with all values externalised to `PROXY_*` environment variables

## What must never be committed

| File | Reason |
|---|---|
| `patterns.conf` | Injection detection signatures — internal to the operator |
| `classifier-prompt.txt` | Gate 2 classifier system prompt — internal to the operator |
| `.env` | Credentials and tokens |
| `openclaw.json` | Live provider config including messaging tokens |
| Real hostnames, IPs, usernames | Exposes personal infrastructure |
| Numeric security thresholds | SSH `Max*`, fail2ban `bantime`/`findtime`/`maxretry` |

These files are excluded by `.gitignore`. If you accidentally stage one, run
`git reset HEAD <file>` before committing.

---

## Making changes to proxy.py

- All tunable constants must use `os.environ.get("PROXY_*", "<default>")` — never hardcode values
- `PROXY_LISTEN_PORT` has no default by design; the proxy exits if it is not set
- If you add a new tunable, also add a corresponding `Environment=` placeholder line to
  `config/etc/systemd/system/ollama-proxy.service` and document it in
  `docs/04-docker-openclaw.md`
- Injection patterns must never be added to `proxy.py` — they belong in `patterns.conf`
  on the target system

---

## Making changes to configuration templates

- After editing a template, verify no real values have been introduced
- If adding a new config file, add it to the file map table in `config/README.md`
- If the file contains sensitive values, add it to `.gitignore` and provide a `.template`
  version only

---

## Secrets scanning

This project uses [`detect-secrets`](https://github.com/Yelp/detect-secrets) to prevent
accidental credential commits. The baseline is stored in `.secrets.baseline`.

To run the scan locally:

```bash
pip install detect-secrets
detect-secrets scan --baseline .secrets.baseline
git diff --exit-code .secrets.baseline
```

If a false positive is flagged, update the baseline:

```bash
detect-secrets audit .secrets.baseline
```

Then commit the updated `.secrets.baseline` alongside your changes.

---

## Markdown linting

All `.md` files are linted by `markdownlint-cli2` in CI. Run the same check locally before
pushing:

```bash
npx markdownlint-cli2 "**/*.md" "#node_modules"
```

Or install once globally and omit `npx`:

```bash
npm install -g markdownlint-cli2
markdownlint-cli2 "**/*.md" "!node_modules"
```

Rules are configured in `.markdownlint.json`. The most common violations are missing blank
lines around fenced code blocks (MD031/MD032), fences without a language tag (MD040), and
missing blank lines around headings (MD022). See `docs/ci-test-guide.md` for annotated
examples of every enforced rule.

---

## Local pre-commit hook

Install this hook once to catch linting and secrets failures before every commit:

```bash
cp scripts/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

The hook runs `markdownlint-cli2` against all staged `.md` files and the
`detect-secrets` baseline check. Any failure blocks the commit with a diagnostic
message. Fix the reported issues and `git add` the corrected files before retrying.

To bypass the hook for a deliberate reason (not recommended for normal use):

```bash
git commit --no-verify
```

---

## Pull request checklist

Before opening a PR, confirm:

- [ ] No real values introduced (hostnames, IPs, credentials, security thresholds)
- [ ] No patterns added to `proxy.py`
- [ ] All new `proxy.py` tunables use the `PROXY_` prefix and `os.environ.get()`
- [ ] `config/README.md` file map updated if config files were added or removed
- [ ] New sensitive files added to `.gitignore` with a `.template` equivalent provided
- [ ] `detect-secrets` baseline passes locally (`detect-secrets scan --baseline .secrets.baseline`)
- [ ] Markdown linting passes locally (`markdownlint-cli2 "**/*.md" "!node_modules"`)

---

## Commit messages

No strict convention is enforced. Please write a clear, present-tense subject line that
describes what the commit does, for example:

```text
Add AppArmor profile for OpenClaw container
Fix proxy num_ctx cap not applying to streaming requests
Clarify fail2ban threshold placeholder in deployment guide
```

---

## Questions

If you have a question about deploying or configuring the stack that is not answered by the
docs, open a [Config Question](https://github.com/mcleo-d/openclaw-pi-oss/issues/new?template=config_question.md)
issue. For security concerns, see [SECURITY.md](SECURITY.md).
