# Threat model

Lightweight, Phase 0. It covers what exists today and the risks the architecture
must be ready for.

**No formal security audit or penetration test has been performed.**

---

## Scope today

|                |                                                                            |
| -------------- | -------------------------------------------------------------------------- |
| Deployed       | Nothing. Local development only.                                           |
| User data      | None. No accounts, no location, no analytics, no cookies.                  |
| Authentication | None. Nothing to authenticate.                                             |
| Attack surface | Two unauthenticated health endpoints, a static frontend, a local database. |
| External calls | Map tiles, browser → provider, direct.                                     |

Most of what follows is therefore about _not building in_ problems that would be
expensive to remove later.

---

## Assets

| Asset                    | Value today   | Value later                                                    |
| ------------------------ | ------------- | -------------------------------------------------------------- |
| Origin/destination pairs | Not collected | **Very high** — reveals home, workplace, clinic, routine       |
| Accessibility reports    | Not collected | **High** — can reveal a contributor's disability and movements |
| Pedestrian graph         | Not built     | Medium — rebuildable, but expensive                            |
| Model + dataset          | Do not exist  | High — the main artefact of Phase 3                            |
| Repository and CI        | Exists        | High — a supply-chain foothold                                 |
| Product trustworthiness  | Exists        | **Critical** — a wrong accessibility claim can strand someone  |

---

## T1 — Future location privacy

**Risk.** Origin/destination pairs are among the most revealing data a person can
hand over. A wheelchair user's routine trips can expose their home, their
workplace and their clinic. Retained with an identifier, they are a movement
profile.

**Why it matters now.** Once route logging exists "for debugging", removing it is
a fight. The cheapest time to decide is before the first line.

**Mitigations.**

- Phase 0 collects nothing. No accounts, no analytics, no tracking cookies.
- `Permissions-Policy: geolocation=()` — the browser is told to refuse geolocation
  outright.
- Route requests, when they exist, must be answerable **without** an identifier.
- Full origin/destination pairs must not be written to application logs, and
  request logging must remain path-only.
- Any retention needs an explicit, documented purpose and a defined lifetime.

**Residual.** Reverse proxies and hosting providers log IP addresses. Unresolved
until a deployment decision is made.

---

## T2 — Future accessibility-report sensitivity

**Risk.** "I could not get up this kerb" reveals both a disability and a
location, at a time. Enough reports from one person reconstruct their movements.
Disability status is sensitive personal information.

**Mitigations (design constraints for Phase 2).**

- Reports must be storable **without** a reporter identifier.
- If reputation is needed, use a pseudonymous token, not an account.
- Never expose a reporter's history publicly.
- Coarsen timestamps in any published derived dataset.
- Say plainly, at submission time, what will be published.

---

## T3 — Misleading accessibility claims (safety)

**This is the highest-severity risk in the project, and it is not a security
vulnerability in the usual sense.**

**Risk.** A route presented as accessible that is not can strand a wheelchair
user far from home, possibly after dark, possibly in winter. The harm is
physical, and it is caused by the product working exactly as coded.

**Mitigations.**

- Phase 0 states prominently that there is no routing and no ML, and that nothing
  shown should be used to plan a journey. Frontend tests assert the disclosure is
  present and that no routing controls exist.
- No route may ever be labelled "accessible" without qualification.
- Confidence and data age must be shown, not hidden behind a clean UI.
- The two error directions are **not symmetric**: a false "passable" is far worse
  than a false "impassable". Cost functions and thresholds must encode that.
- Deterministic rules must never be described as AI.

**Residual.** Fundamental to the product. Managed by honesty, never eliminated.

---

## T4 — Missing-data optimism

**Risk.** The subtle version of T3. If an edge has no barrier recorded, the
system must not treat it as barrier-free. Absence of evidence is not evidence of
absence, and OSM accessibility tagging is sparse and uneven — the areas with the
least data are often the least surveyed, which correlates with the areas most
likely to be inaccessible.

**Mitigations.**

- The data model must distinguish "no barrier" from "no data" as separate states,
  not one nullable column.
- Coverage must be surfaced in the UI: "we have little data here" is a valid,
  useful answer.
- Routing must penalise unknown segments for profiles with hard constraints,
  rather than treating unknown as clear.

---

## T5 — Future report manipulation

**Risk.** Anonymous reports invite abuse: a business suppressing a barrier report,
a bad actor marking a competitor's street impassable, or bulk false reports
poisoning the graph.

**Mitigations (Phase 2 design).**

- Corroboration before a report changes routing.
- Rate limiting per source.
- Divergence from OSM or municipal data flags for review rather than
  auto-applying.
- Report provenance retained for audit even when the reporter is not identified.
- Reports are evidence, never authoritative overrides.

---

## T6 — Oversized or malicious requests

**Risk.** Unbounded input consumes memory or CPU. A future route request with an
enormous bounding box, thousands of waypoints, or absurd coordinates is a cheap
denial of service.

**Current state.** Every input is bounded by a Pydantic constraint rather than a
manual check, so an out-of-range value is rejected by the schema before any code
sees it: longitude and latitude to the WGS84 range, region slugs to 64 characters
matching `^[a-z0-9-]+$`, search text to 160 characters, result limits to 5.

Routing work is bounded three ways, all in `routing/engine.py`:

| Bound                  | Value | Why                                                             |
| ---------------------- | ----- | --------------------------------------------------------------- |
| `MAX_REQUEST_SPAN_M`   | 15 km | Refused before any search runs; not a walking journey           |
| `MAX_SNAP_DISTANCE_M`  | 300 m | A point further than this from any path is refused, not guessed |
| `MAX_EDGE_EVALUATIONS` | 750 k | The search aborts rather than expanding a pathological request  |

`RequestSizeLimitMiddleware` rejects a declared `Content-Length` above 64 KiB
before the body is read — three orders of magnitude above a real request. It runs
first, ahead of correlation logging, so nothing else is spent on an oversized
body.

Readiness still has a bounded timeout, so a hung database cannot hold a request
open indefinitely.

**Still required before public deployment.**

- **Chunked bodies without a `Content-Length` are not bounded here.** Measuring
  one means consuming the stream, which is the cost the middleware exists to
  avoid; bounding it belongs to the reverse proxy in front of the service.
- Rate limiting. There is none, and nothing in this service authenticates
  callers.
- A wall-clock timeout per request, in addition to the edge budget. The budget
  bounds work, not time, and a heavily loaded machine can be slow within it.

---

## T7 — Dependency compromise

**Risk.** A malicious version of a transitive dependency runs arbitrary code at
install time in CI or on a developer's machine.

**Mitigations.**

- Lockfiles committed; CI installs with `--frozen-lockfile` / `--frozen`.
- **pnpm postinstall scripts are blocked by default.** `pnpm-workspace.yaml`
  allow-lists exactly one package (`unrs-resolver`) with a stated reason.
- `pip-audit` and `pnpm audit` run on every PR and weekly.
- Dependabot covers Actions, npm, uv and Docker, grouped to keep review
  meaningful.
- Every third-party GitHub Action is pinned to an immutable commit SHA with a
  version comment. A tag can be moved; a SHA cannot.
- CI uses `permissions: contents: read` and needs no secrets, so a compromised
  dependency in a PR run has nothing to steal.

**Residual.** A compromised pinned version is still trusted until the audit
catches it. Weekly scheduled scans shorten that window.

---

## T8 — Secret exposure

**Risk.** A credential committed to git, baked into an image, or inlined into the
browser bundle. Git history makes a committed secret effectively permanent.

**Mitigations.**

- `.env` git-ignored; `.env.example` carries placeholders only, with the database
  password named `pathable_local_dev_only`.
- gitleaks scans **full history** in CI, not just the diff.
- A CI check fails the build if any environment file becomes tracked.
- A CI check rejects `NEXT_PUBLIC_*KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL` —
  anything with that prefix is compiled into the client bundle and readable by
  every visitor.
- Images contain no `.env` and no credentials; configuration arrives at runtime.
  CI asserts this by inspecting the built API image.

---

## T9 — Map and geocoding provider misuse

**Risk.** Two directions. Exceeding a free provider's capacity is both an outage
for us and abuse of a donated community resource. Conversely, a provider outage
becomes a PathAble outage.

**Mitigations.**

- OSM-operated tile and Nominatim services are explicitly not used for
  application traffic ([ADR 0005](../adr/0005-map-and-geocoding-providers.md)).
- The tile provider is configuration, so switching is a `.env` change.
- The map has a documented failure state with a written fallback, so a tile
  outage degrades rather than breaks the page.
- No test depends on public tile availability.

**Residual.** The default provider has no SLA. Flagged as a founder decision
before any public deployment.

---

## T10 — Information disclosure through errors and logs

**Risk.** Stack traces, connection strings or driver messages leaking through an
unauthenticated endpoint. psycopg failure text routinely embeds host, port,
database and user.

**Mitigations.**

- One error envelope for all non-2xx responses; unhandled exceptions return a
  fixed generic message with a correlation id.
- Readiness returns a fixed `"database unreachable"` string; the exception is
  logged, never returned.
- Validation errors forward only `loc` and `msg` — Pydantic's `input` and `ctx`
  would reflect caller-controlled data straight back out.
- Only `host:port/database` is ever logged, via `safe_database_target()`.
- Interactive API docs are disabled in production.
- `X-Powered-By` removed; `nosniff`, `DENY` framing and a strict referrer policy
  set.

Tests assert that a deliberately leaky exception message and a password-bearing
DSN never appear in a response body.

---

## Out of scope for Phase 0

Not because they do not matter, but because the thing they protect does not exist
yet: authentication and session security, authorisation, CSRF, DDoS protection,
infrastructure hardening, backup and recovery, incident response, and GDPR/PIPEDA
compliance processes.

Each becomes in scope at the phase that introduces its asset.

---

## Review triggers

Revisit this document when any of the following first happens: the application is
deployed anywhere public; any personal data is collected; authentication is
added; user reports are accepted; imagery is ingested; a model affects a route;
or a third-party service becomes a runtime dependency.
