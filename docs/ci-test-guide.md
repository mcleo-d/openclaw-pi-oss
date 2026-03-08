# CI Test Guide

This guide documents every check that runs in `.github/workflows/ci.yml`, explains why each
check exists, and shows you how to reproduce it exactly on your local machine before pushing.
It is intended for contributors who have never seen the project before.

The pipeline runs on every push and pull request targeting `main`. There are four jobs:

1. [secrets-scan](#1-secrets-scan) — detect accidentally committed credentials
2. [placeholder-check](#2-placeholder-check) — ensure deployable config files have no unfilled template tokens
3. [markdown-lint](#3-markdown-lint) — enforce consistent Markdown style
4. [proxy-syntax](#4-proxy-syntax) — verify `proxy.py` is valid Python

All four jobs run in parallel. A pull request is blocked if any job fails.

---

## Prerequisites

Install the tools listed below before running any check locally. All are either Python packages
or Node.js packages installed from the official registries; none require root.

```bash
# detect-secrets (exactly the version CI uses)
pip install detect-secrets==1.5.0

# markdownlint-cli2 (matches the action version used in CI)
npm install -g markdownlint-cli2

# python3 is required for the proxy syntax check
# It ships with macOS (Homebrew python3) and most Linux distributions.
python3 --version   # must be 3.9 or later
```

---

## 1. secrets-scan

### What it checks and why

`detect-secrets` scans every file in the repository for patterns that resemble credentials:
API keys, tokens, high-entropy strings, AWS key IDs, private keys, and more. It uses a baseline
file (`.secrets.baseline`) that records every known finding that has been reviewed and accepted
as a false positive. If the scan produces any result that is not already in the baseline, CI
fails.

This job exists because a single committed credential — a real API key, a database password, a
private key — can be scraped from a public repository within seconds. Fixing a credential leak
after the fact requires rotating the credential and auditing all access since the commit landed.
Prevention is far cheaper.

### The baseline workflow

`.secrets.baseline` is a JSON file that detect-secrets maintains. It has three important sections:

- `plugins_used` — the list of detectors that were active when the baseline was generated. This
  must stay stable; adding or removing a plugin causes a baseline mismatch.
- `filters_used` — heuristic filters that reduce false-positive noise (for example,
  `is_potential_uuid` suppresses UUID-shaped strings).
- `results` — the accepted findings keyed by file path. Each entry records the detector type,
  a SHA-1 hash of the detected value, and the line number.

The `generated_at` field records the timestamp of the last scan. It changes on every run,
including in CI. The CI script explicitly filters this field out of the diff so that a timestamp
change alone does not cause a failure.

The `hashed_secret` field contains `SHA1(secret_value)`. The raw secret is never stored; only
the hash is committed. This lets detect-secrets verify that the accepted finding has not changed
(if the line content changes, the hash no longer matches and the entry is treated as a new
finding) without storing the actual value in the repository.

### The `is_baseline_file` filter

detect-secrets 1.5.0 automatically adds a filter called `is_baseline_file` when you run
`detect-secrets scan`. This filter tells detect-secrets to skip scanning the baseline file
itself (`.secrets.baseline`) — otherwise the hashes stored inside it would trigger the
high-entropy string detector. You do not need to add this filter manually; it is applied
automatically when the `--baseline` flag is used.

### Currently baselined false positives

There is one accepted finding at the time of writing:

| File | Line | Type | Why it is safe |
|---|---|---|---|
| `docs/05-ollama-model-research.md` | 334 | Secret Keyword | The value `"apiKey": "ollama-local"` is a conventional placeholder shown in example OpenClaw provider config. Ollama does not perform any API key validation; it accepts any non-empty string in this field. `ollama-local` is a widely used conventional value for this purpose and is not a real credential. |

If you add a new false positive, you must audit it using the process described below before
committing the updated baseline.

### Local commands

Run the scan from the repository root:

```bash
detect-secrets scan --baseline .secrets.baseline
```

Then check whether the baseline changed beyond the timestamp:

```bash
git diff .secrets.baseline | grep -v '"generated_at"' | grep -E '^\+[^+]|^-[^-]' | grep -q '.' \
  && echo "FAIL: unexpected baseline changes" \
  || echo "PASS: no unexpected baseline changes"
```

This is exactly what CI runs. The two-step approach — scan then diff — means CI catches both
new secrets (new entries in `results`) and structural changes to the baseline (plugin list
changed, filter list changed).

### What a pass looks like

```
PASS: no unexpected baseline changes
```

The scan produces no output on success. The diff command produces no output and exits 0.

### What a fail looks like

```
FAIL: unexpected baseline changes
```

Followed by a unified diff of `.secrets.baseline` showing the new or changed entry. CI also
prints the full diff to the job log.

A new `results` entry looks like this in the diff:

```diff
+    "path/to/file.py": [
+      {
+        "type": "Secret Keyword",
+        "filename": "path/to/file.py",
+        "hashed_secret": "da39a3ee5e6b4b0d3255bfef95601890afd80709",
+        "is_verified": false,
+        "line_number": 42
+      }
+    ],
```

### Common failure causes and fixes

**You added a line that resembles a credential.**

Open the file at the indicated line. If the value is genuinely a secret, remove it, rotate
the credential, and check your shell history for accidental exposure. If it is a false positive
(a test fixture, a documentation example, a placeholder), run the audit workflow below.

**You renamed or deleted a file that had an accepted finding.**

detect-secrets tracks findings by file path. If you rename `docs/foo.md` to `docs/bar.md`, the
old entry in `results` becomes stale and the new path is treated as a new finding. Fix: re-run
the audit workflow after the rename.

**You changed a plugin's configuration in `.secrets.baseline` manually.**

Do not edit `.secrets.baseline` by hand. Always let `detect-secrets scan` generate it.

### Adding a false positive to the baseline

When `detect-secrets scan` flags a value that is genuinely not a secret, use the interactive
audit tool:

```bash
detect-secrets audit .secrets.baseline
```

The audit tool presents each new finding and asks you to classify it. Press `y` to mark it as
a real secret (which prompts you to remove it) or `n` to mark it as a false positive (which
accepts it into the baseline). After auditing, commit the updated `.secrets.baseline` alongside
the file that triggered the finding, with a commit message explaining why it is a false positive.

Do not mark a finding as a false positive if you are not certain the value is safe. When in
doubt, treat it as a real secret and rotate it.

### Known gotcha: `generated_at` always changes

Every time you run `detect-secrets scan`, the `generated_at` timestamp is updated to the
current UTC time. This means `.secrets.baseline` will always appear dirty after a scan. Do not
commit `.secrets.baseline` after every local scan; only commit it when the `results` section
has genuinely changed (new false positive accepted, stale entry removed). CI handles this
correctly by filtering `generated_at` out of the diff check.

---

## 2. placeholder-check

### What it checks and why

This job scans a specific list of deployable configuration files for the token `<your-`. Files
in this project use `<your-value>` placeholders to mark fields that operators must fill in
before deploying. Deployable files — those intended to be copied directly onto the Pi without
further templating — must not contain these placeholders. If they do, the configuration is
broken: a service will either fail to start or will connect to a literal hostname like
`<your-pi-hostname>`.

Template files (those with a `.template` extension) and documentation files are intentionally
excluded from this check because they are expected to document placeholders.

### Files checked

The following files are checked. All must be free of `<your-` tokens:

- `config/etc/docker/daemon.json`
- `config/etc/sysctl.d/99-hardening.conf`
- `config/etc/apt/apt.conf.d/50unattended-upgrades`
- `config/etc/apt/apt.conf.d/20auto-upgrades`
- `config/etc/systemd/system/ollama.service.d/override.conf`
- `config/etc/ollama-proxy/proxy.py`

### Local command

```bash
files=(
  "config/etc/docker/daemon.json"
  "config/etc/sysctl.d/99-hardening.conf"
  "config/etc/apt/apt.conf.d/50unattended-upgrades"
  "config/etc/apt/apt.conf.d/20auto-upgrades"
  "config/etc/systemd/system/ollama.service.d/override.conf"
  "config/etc/ollama-proxy/proxy.py"
)
failed=0
for f in "${files[@]}"; do
  if grep -q '<your-' "$f"; then
    echo "ERROR: unfilled placeholder found in $f"
    failed=1
  fi
done
exit $failed
```

Run this from the repository root.

### What a pass looks like

No output. Exit code 0.

### What a fail looks like

```
ERROR: unfilled placeholder found in config/etc/docker/daemon.json
```

Exit code 1.

### Common failure causes and fixes

**You introduced a new `<your-` placeholder in a deployable file.**

If the value is genuinely operator-specific, it belongs in a `.template` file, not in the
deployable file. Move it there, or replace the placeholder with a safe default if one exists.
If the file is a template that was accidentally added to the checked list, the CI script needs
to be updated — open a PR that moves it to the correct category and adds it to `.gitignore`
if it contains sensitive values.

**You copied a template into a deployable path without filling in the placeholders.**

Fill in the values. If the values are sensitive (hostnames, credentials), ensure they are
never committed — add the filled-in file to `.gitignore` and rely on the `.template` version
for source control.

### Known gotcha: only six files are checked

The check is an explicit allowlist, not a recursive scan of `config/`. Adding a new deployable
config file to `config/` does not automatically include it in this check. When you add a new
deployable config file, add its path to the `files` array in `.github/workflows/ci.yml` in the
same PR.

---

## 3. markdown-lint

### What it checks and why

Every `.md` file in the repository (excluding `node_modules`) is linted by `markdownlint-cli2`
using the rules defined in `.markdownlint.json`. The linter enforces consistent Markdown
structure: heading hierarchy, blank lines around blocks, fenced code block language tags, and
so on. Consistent Markdown renders correctly across GitHub, documentation sites, and editors.
Inconsistent Markdown can render differently depending on the parser — a missing blank line
before a code fence, for example, causes some parsers to include the fence markers in the
paragraph above.

### Active rules

`"default": true` enables all markdownlint rules. Four rules are then explicitly disabled (see
the next section). The active rules include, but are not limited to:

| Rule | What it enforces |
|---|---|
| MD001 | Heading levels must increment by one at a time |
| MD003 | Heading style must be consistent (ATX `##` style by default) |
| MD004 | Unordered list style must be consistent |
| MD005 | List indentation must be consistent |
| MD007 | Unordered list indentation must be consistent |
| MD009 | No trailing spaces |
| MD010 | No hard tabs |
| MD011 | Reversed link syntax `(text)[url]` is not allowed |
| MD014 | Dollar signs before shell commands in code blocks only when showing output |
| MD018 | Space required after `#` in ATX headings |
| MD019 | No multiple spaces after `#` in ATX headings |
| MD022 | Headings must be surrounded by blank lines |
| MD023 | Headings must start at the beginning of the line |
| MD024 | No duplicate heading text within the same document |
| MD025 | Only one top-level heading per document |
| MD026 | No trailing punctuation in headings |
| MD027 | No multiple spaces after blockquote symbol |
| MD028 | No blank line inside blockquote |
| MD029 | Ordered list item prefix must be consistent |
| MD030 | Spaces after list markers must be consistent |
| MD031 | Fenced code blocks must be surrounded by blank lines |
| MD032 | Lists must be surrounded by blank lines |
| MD034 | No bare URLs |
| MD035 | Horizontal rule style must be consistent |
| MD036 | Emphasis used instead of a heading |
| MD037 | No spaces inside emphasis markers |
| MD038 | No spaces inside code span |
| MD039 | No spaces inside link text |
| MD040 | Fenced code blocks must have a language identifier |
| MD042 | No empty links |
| MD043 | Required heading structure (if configured) |
| MD044 | Proper name capitalisation |
| MD045 | Images must have alt text |
| MD046 | Code block style must be consistent |
| MD047 | File must end with a single newline |
| MD048 | Code fence style must be consistent |
| MD049 | Emphasis style must be consistent |
| MD050 | Strong style must be consistent |

### Disabled rules

| Rule | Reason disabled |
|---|---|
| MD012 (no-multiple-blanks) | Multiple consecutive blank lines are used intentionally in some documents to create visual separation between major sections. Enforcing single blank lines would require altering deliberate layout decisions. |
| MD013 (line-length) | This project contains long tables and command examples in documentation. A strict line length limit would force wrapping in contexts where wrapping degrades readability (URLs, table cells, inline code). |
| MD033 (no-inline-html) | Some documents include raw HTML for elements that Markdown cannot express, such as `<details>` disclosure widgets. Blocking all inline HTML would prohibit this. |
| MD041 (first-line-heading) | Several files served as GitHub templates (issue templates, pull request template, agent definition files) legitimately begin with front matter or a non-heading line. Requiring every file to start with an `# H1` heading would break these files. |

### Rules contributors most commonly violate

#### MD031 — fenced code blocks must be surrounded by blank lines

A blank line is required before the opening fence and after the closing fence.

Wrong:

```text
Some text.
```bash
echo hello
```
More text.
```

Correct:

```text
Some text.

```bash
echo hello
```

More text.
```

Note: the blank line after the closing fence is also required. A closing fence immediately
followed by text is a common mistake because the rendered output looks fine in many editors
but fails the linter.

#### MD032 — lists must be surrounded by blank lines

A blank line is required before the first list item and after the last list item.

Wrong:

```text
See the following:
- Item one
- Item two
Continue reading.
```

Correct:

```text
See the following:

- Item one
- Item two

Continue reading.
```

This applies to both unordered (`-`, `*`, `+`) and ordered (`1.`, `2.`) lists.

#### MD040 — fenced code blocks must have a language identifier

Every fenced code block must declare its language. If the content has no syntax to highlight,
use `text` or `plaintext`.

Wrong:

````text
```
some output here
```
````

Correct:

````text
```text
some output here
```
````

Common language identifiers used in this project: `bash`, `json`, `python`, `yaml`, `text`,
`ini`, `toml`, `plaintext`.

#### MD022 — headings must be surrounded by blank lines

A blank line is required before and after every heading.

Wrong:

```text
Some paragraph.
## Section heading
Content here.
```

Correct:

```text
Some paragraph.

## Section heading

Content here.
```

The blank line before the first heading in a document is not required if the heading is the
very first line, but a blank line after it is always required before the first content.

### Local command

Run from the repository root:

```bash
markdownlint-cli2 "**/*.md" "!node_modules"
```

### What a pass looks like

No output. Exit code 0.

### What a fail looks like

```
docs/01-hardware.md:42:1 MD031/blanks-around-fences Fenced code blocks should be surrounded by blank lines [Context: "```"]
docs/03-security-hardening.md:88 MD040/fenced-code-language Fenced code blocks should have a language specified [Context: "```"]
```

Each line is `file:line:column rule-id/rule-name description [Context: "..."]`. The context
shows the content of the offending line to help you locate it.

Exit code is non-zero when any violation is found.

### Common failure causes and fixes

**MD031 or MD032 in a newly written section.** Add the missing blank lines around code fences
and lists. Most editors with a Markdown preview will not show these as errors, so they are easy
to miss.

**MD040 on a code block copied from elsewhere.** Add the language identifier to the opening
fence.

**MD022 after inserting a heading mid-document.** Check that there is a blank line both before
and after the new heading, not just one side.

**MD024 duplicate heading.** GitHub renders in-page anchor links from heading text, so duplicate
headings break anchor navigation. Reword one of the duplicates to be unique.

**MD047 file must end with a newline.** Most editors handle this automatically, but some do not.
If your file fails this rule, add a newline at the end of the file.

### Known gotchas

**MD041 is disabled for a reason.** Issue templates, the pull request template, and agent
definition files all start without an H1 heading. If you are linting a new file and getting an
MD041 violation, check whether the file genuinely needs the rule waived. If it does, the
existing disable in `.markdownlint.json` already covers all `.md` files. If you are writing
a normal documentation file, add the H1 heading rather than relying on the global disable.

**The glob pattern matches all `.md` files recursively.** This includes files in `.claude/`,
`.github/`, and `config/`. When you add a new `.md` file anywhere in the repository, it is
linted automatically — you do not need to register it anywhere.

**markdownlint-cli2 vs markdownlint-cli.** CI uses `markdownlint-cli2` (the newer tool). The
command syntax is slightly different from the older `markdownlint` CLI. If you have `markdownlint`
installed instead, the glob syntax and configuration loading differ. Install `markdownlint-cli2`
to match CI exactly.

---

## 4. proxy-syntax

### What it checks and why

`config/etc/ollama-proxy/proxy.py` is the Ollama proxy that intercepts requests from OpenClaw
and applies security controls (prompt injection detection, context window capping, system
message truncation). The proxy is deployed as a systemd service on the Pi. A Python syntax
error in this file would cause the service to fail to start at the next deployment.

This job runs `python3 -m py_compile` against the file to catch syntax errors without executing
any code. It does not check logic, types, or runtime behaviour — only that the file can be
parsed by Python.

Note that `py_compile` verifies syntax only. It does not import the module or run any
module-level code, so it does not require the `PROXY_LISTEN_PORT` environment variable (which
`proxy.py` requires at startup) to be set.

### Local command

Run from the repository root:

```bash
python3 -m py_compile config/etc/ollama-proxy/proxy.py && echo "PASS" || echo "FAIL"
```

### What a pass looks like

```
PASS
```

No output from `py_compile` itself. Exit code 0.

### What a fail looks like

```
  File "config/etc/ollama-proxy/proxy.py", line 87
    def broken_function(
                       ^
SyntaxError: '(' was never closed
FAIL
```

The error message includes the file path, line number, a caret pointing to the problem, and a
description.

### Common failure causes and fixes

**Mismatched parentheses, brackets, or braces.** Python's syntax error messages are usually
accurate about location. Check the line indicated and the lines before it for unclosed delimiters.

**Invalid type annotation syntax for the Python version.** `proxy.py` uses `tuple[bool, str]`
syntax (PEP 585 built-in generics), which requires Python 3.9 or later. If you are running
Python 3.8, this will produce a `TypeError` at parse time. Upgrade to Python 3.9+.

**Incomplete edit.** If you interrupted an edit and left the file in an inconsistent state,
restore it with `git checkout config/etc/ollama-proxy/proxy.py`.

### Known gotchas

**py_compile does not run the module.** The module-level code in `proxy.py` calls
`_load_patterns()` and `_load_classifier_prompt()`, which read files from the filesystem and
call `sys.exit(1)` if those files are missing. If you were to run `proxy.py` directly (with
`python3 proxy.py`), it would fail unless `PROXY_LISTEN_PORT` is set and both
`PROXY_PATTERNS_FILE` and `PROXY_CLASSIFIER_SYSTEM_PROMPT_FILE` exist. `py_compile` avoids
this entirely — it only parses the AST.

**Python version must be 3.9 or later.** This matches the `CONTRIBUTING.md` prerequisite. If
`python3 --version` returns anything below 3.9, the syntax check may produce false failures on
type annotation syntax.

---

## Pre-push checklist

Run these commands top-to-bottom from the repository root before opening a pull request. Each
block corresponds to one CI job. A clean run of all four blocks means CI will pass.

### Step 1 — Secrets scan

```bash
detect-secrets scan --baseline .secrets.baseline

git diff .secrets.baseline \
  | grep -v '"generated_at"' \
  | grep -E '^\+[^+]|^-[^-]' \
  | grep -q '.' \
  && echo "FAIL: secrets baseline has unexpected changes; run 'detect-secrets audit .secrets.baseline' to review" \
  || echo "PASS: secrets scan clean"
```

If the baseline changed with new entries in `results`, run the audit before continuing:

```bash
detect-secrets audit .secrets.baseline
```

### Step 2 — Placeholder check

```bash
files=(
  "config/etc/docker/daemon.json"
  "config/etc/sysctl.d/99-hardening.conf"
  "config/etc/apt/apt.conf.d/50unattended-upgrades"
  "config/etc/apt/apt.conf.d/20auto-upgrades"
  "config/etc/systemd/system/ollama.service.d/override.conf"
  "config/etc/ollama-proxy/proxy.py"
)
failed=0
for f in "${files[@]}"; do
  if grep -q '<your-' "$f"; then
    echo "FAIL: unfilled placeholder in $f"
    failed=1
  fi
done
[ "$failed" -eq 0 ] && echo "PASS: placeholder check clean"
exit $failed
```

### Step 3 — Markdown lint

```bash
markdownlint-cli2 "**/*.md" "!node_modules" && echo "PASS: markdown lint clean"
```

### Step 4 — Proxy syntax

```bash
python3 -m py_compile config/etc/ollama-proxy/proxy.py \
  && echo "PASS: proxy syntax clean" \
  || echo "FAIL: proxy.py syntax error (see above)"
```

### Step 5 — Manual checks from CONTRIBUTING.md

These are not automated in CI but are part of the pull request review:

- No real values introduced (hostnames, IP addresses, credentials, numeric security thresholds
  such as `maxretry`, `bantime`, `MaxAuthTries`)
- Injection patterns not added to `proxy.py` (they belong in `patterns.conf` on the Pi)
- All new `proxy.py` tunables use `os.environ.get("PROXY_*")` and are documented in
  `docs/04-docker-openclaw.md` and `config/etc/systemd/system/ollama-proxy.service`
- `config/README.md` file map updated if any config files were added or removed
- New sensitive files added to `.gitignore` with a `.template` equivalent provided

---

## Quick-reference: tool versions used in CI

| Tool | Version pinned in CI | Install command |
|---|---|---|
| detect-secrets | 1.5.0 (`.github/requirements-ci.txt`) | `pip install detect-secrets==1.5.0` |
| markdownlint-cli2 | v16 (action `b4c9feab`) | `npm install -g markdownlint-cli2` |
| python3 | system python on `ubuntu-latest` (3.12 as of 2026) | Ships with OS; must be >= 3.9 |

Pin `detect-secrets` to exactly `1.5.0` to avoid baseline format drift. The `generated_at`
filter and `is_baseline_file` auto-filter behaviour are version-specific; a newer release may
change the baseline schema in ways that trigger false failures.
