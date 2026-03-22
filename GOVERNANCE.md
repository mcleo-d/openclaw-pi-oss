# Governance

`openclaw-pi-oss` is a personal open-source project maintained by James McLeod.
This document explains how decisions are made, how to become a maintainer, and
how the project handles its community responsibilities.

---

## Project model

This is a **benevolent dictatorship** project. The maintainer makes final decisions
after consulting the community. There is no steering committee or formal voting.

This is appropriate for the project's current scale: a focused reference deployment
with a narrow scope. If the project grows significantly in contributors or adoption,
governance will evolve — changes will be documented here first.

---

## Decision types

### Minor changes

Definition: documentation corrections, typos, template clarifications, small bug
fixes, CI maintenance, Dependabot updates.

Process:

- Open a PR.
- CI must pass.
- Maintainer merges when satisfied. No waiting period.

### Major changes

Definition: new features, proxy architecture changes, new security controls,
changes to the hardening model, new hardware support, roadmap items.

Process:

1. Open a GitHub issue describing the proposed change, motivation, and approach.
2. Community discussion period: **7 days minimum** before implementation begins.
3. Maintainer summarises feedback and announces the decision in the issue.
4. Implementation proceeds via a PR, referencing the discussion issue.
5. Maintainer merges when CI passes and the implementation matches the agreed design.

### Security changes

Definition: vulnerability fixes, hardening improvements, changes to injection
detection, changes to secrets handling.

Process: handled privately per [SECURITY.md](SECURITY.md). Security fixes are
applied to `main` without a public discussion period. A GitHub Security Advisory
is published after the fix is available.

---

## Maintainers

| Name | Role | GitHub |
|---|---|---|
| James McLeod | Founder, maintainer | [@mcleo-d](https://github.com/mcleo-d) |

The maintainer is responsible for:

- Reviewing and merging PRs
- Triaging issues
- Publishing security advisories
- Keeping this document and SECURITY.md current

---

## Becoming a maintainer

There is no formal application process. Contributors who submit 3–5 significant,
well-reviewed contributions — across code, documentation, hardware testing, or
security review — become eligible for maintainer status.

The maintainer will reach out directly. If you believe you meet this bar and have
not been contacted, open an issue and ask.

Maintainer offboarding: a maintainer who is inactive for 12 months or who requests
removal will be moved to an Emeritus Maintainers section of this document.

---

## Support expectations

This is a hobby project. There is no SLA.

- Issues: triaged within 14 days, best effort
- PRs: reviewed within 7–14 days
- Security reports: acknowledged within 7 days (see SECURITY.md)

If you need faster support, consider hiring a contractor or consulting the
[OpenClaw project](https://openclaw.ai) directly.

---

## Amendments

Changes to this document follow the major-change process above.
