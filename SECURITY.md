# Security policy

## Project status

PathAble AI is pre-release. It routes over a real OpenStreetMap network for one
pilot region, but it is **not deployed anywhere**, holds **no user data**, has
**no authentication**, and runs only on developer machines. The security posture
described here is what the foundation establishes, not a statement that the
system has been audited.

**No formal security audit or penetration test has been performed.**

## Reporting a vulnerability

Report privately. Do not open a public issue for a security problem.

- Preferred: GitHub → **Security** → **Report a vulnerability** (private
  advisory) on this repository.
- Otherwise: contact the maintainer directly through the address on their GitHub
  profile.

Please include what you found, how to reproduce it, and what you think the
impact is. As a pre-release student-led project there is no bounty programme and
no formal SLA; expect an acknowledgement within about a week.

Please do not run automated scanners against any host you do not own. There is
no PathAble deployment to test against.

## Supported versions

Only the `main` branch. There are no releases yet.

## What the foundation enforces

| Control                        | Where                                                        |
| ------------------------------ | ------------------------------------------------------------ |
| No secrets in the repository   | `.env` git-ignored; gitleaks scans full history in CI        |
| No secrets in container images | Nothing but code is copied in; configuration is runtime-only |
| No secret-shaped public config | CI rejects `NEXT_PUBLIC_*KEY/TOKEN/SECRET/PASSWORD`          |
| Non-root containers            | Both images run as uid 10001                                 |
| Restricted CORS                | Explicit origin allow-list; wildcard rejected in production  |
| No credentialed wildcard CORS  | `allow_credentials` is structurally always `false`           |
| Sanitised API errors           | One error envelope; no tracebacks, DSNs or driver messages   |
| No credentials in logs         | Only a `host:port/database` summary is ever logged           |
| Dependency auditing            | `pip-audit` and `pnpm audit` weekly and on every PR          |
| Pinned CI supply chain         | Every third-party action pinned to a commit SHA              |
| Minimal CI permissions         | `contents: read`; no secrets needed for PR CI                |

## Threat model

A lightweight threat model, including the privacy and safety risks specific to
an accessibility routing product, is in
[`docs/security/THREAT_MODEL.md`](docs/security/THREAT_MODEL.md).

Two risks there are worth repeating because they are unusual and serious:

1. **Misleading accessibility claims.** A route presented as accessible when it
   is not can strand a wheelchair user at an unramped kerb after dark. This is a
   safety issue, not a UX issue.
2. **Location privacy.** Origin and destination pairs are among the most
   sensitive data a person can hand over. The system does not collect them today
   and must not begin to without an explicit privacy design.

## Disclosure

Fixes land on `main` and are described in the pull request. Once releases exist,
security-relevant fixes will be called out in the release notes.
