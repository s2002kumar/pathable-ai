# Public-release safety gate

**Verdict: NOT SAFE TO MAKE PUBLIC — for one non-engineering reason.** The
repository holds no secrets, no private data and no restricted datasets, every
scan and audit run for this gate came back clean, and the one attribution gap
found was fixed on this branch. What blocks publication is that the project has
**no licence** ([`LICENSING.md`](../../LICENSING.md)): a public repository with
all rights reserved is a founder decision that has not been made, and it is
listed there as the first release-readiness item. Once a licence is chosen and
the items under _Founder decisions_ below are settled, nothing in this gate
stands in the way.

Assessed 2026-09-07 on `main` at `74825356` (tag `v0.2.0-gate-ab`), with the
two open feature branches and every tag included in the history scan. The
repository was private throughout and remains private; this gate changes no
visibility.

The scanner reports themselves are not committed. They contain nothing, and
that is exactly why a report that one day did contain something must never be
where a public clone could find it.

---

## 1. Secrets

**Tool.** gitleaks `v8.30.1`, the same pinned container image the `Security`
workflow uses, run locally under Docker with `--redact` so no matched value is
ever printed or written.

**Refs scanned.** `git --log-opts="--all --full-history"` against the
repository: 94 commits reachable from every local branch, every
remote-tracking branch (including the 17 open Dependabot branches) and both
tags. Separately, `gitleaks dir` over clean `git archive` exports of the
current trees of `main`, `perf/graph-load` (8cdc5a2) and
`feature/c01-ml-production-readiness` (2766bd0, PR #22).

| Scan                            | Scope               | Findings |
| ------------------------------- | ------------------- | -------- |
| History, all refs               | 94 commits, 2.11 MB | 0        |
| Current tree, `main`            | 247 files           | 0        |
| Current tree, `perf/graph-load` | 254 files           | 0        |
| Current tree, PR #22 head       | 254 files           | 0        |

**Manual inspection**, over tracked files and the full history:

| Category                          | Result                                                                                                                                                                                                      |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Credentials, tokens, private keys | None. `.env` has never been tracked; the only environment file ever committed is `.env.example`. No `.pem`, `.key`, keystore or certificate files at any point in history.                                  |
| Database connection strings       | Only the `.env.example` placeholder (`pathable_local_dev_only`, `localhost`) and the Compose default with the same placeholder. The API logs a `host:port/database` summary only.                           |
| Database dumps, extracts          | None. No `.sql`, `.dump`, `.pbf`, `.osm`, GeoTIFF or archive has ever been tracked. OSM caches and extracts are git-ignored and Docker-ignored.                                                             |
| Private or restricted datasets    | None. No imagery, no university-only data, no ML training set, no model weights (`.pt`, `.onnx`, `.pkl`, `.h5`, `.npy`). PR #22 adds schema and split logic only; its own body says nothing was downloaded. |
| Personal information              | None beyond the maintainer's commit identity (see _Founder decisions_). The 20-journey evaluation corpus uses public landmarks. Route requests are never stored (ADR 0007).                                 |
| Machine-specific paths            | None in tracked files. `C:\Users`, `/home/<user>` and the developer's account name appear nowhere.                                                                                                          |
| Generated artifacts               | Only six evidence screenshots (largest 550 KB) and the committed contracts (`openapi.json`, `api.ts`, regenerated and drift-checked in CI). Build, coverage, test and report directories are ignored.       |

## 2. Configuration fails closed

- Every value in `.env.example` is an obvious non-production placeholder:
  loopback hosts, `pathable_local_dev_only`, an empty geocoding contact, a free
  development tile style that the file itself says is not approved for
  production.
- In `production` the settings model refuses to start without `DATABASE_URL`,
  without at least one explicit origin, with a `*` origin, or without JSON
  logs, and reports every problem at once. Credentialed CORS is structurally
  impossible. Interactive API docs are disabled. Covered by the configuration
  unit tests (96 passed for config, error envelope and logging on this branch).
- Container images copy no environment file and carry no credential; both run
  as uid 10001; `.dockerignore` excludes `.env*`, `.git` and every state
  directory. Web build arguments are `NEXT_PUBLIC_*` only, and CI rejects any
  secret-shaped name under that prefix.

## 3. Dependencies

**Advisories.**

| Audit                                                    | Result                   |
| -------------------------------------------------------- | ------------------------ |
| `pip-audit --strict` over the exported lock (all groups) | No known vulnerabilities |
| `pnpm audit` (all severities)                            | No known vulnerabilities |

**Licence inventory** (engineering facts; not legal conclusions).

| Ecosystem | Packages | Permissive (MIT/BSD/Apache/ISC/PSF/MPL/0BSD/CC0/BlueOak) | Copyleft                                                                                                                | Unknown                                                      |
| --------- | -------- | -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| Python    | 68       | 64                                                       | 3 (LGPL-3.0: `psycopg`, `psycopg-binary`, `psycopg-pool`)                                                               | 0 (`pathable-api` itself is declared proprietary/unreleased) |
| Node      | 466      | 465                                                      | 1 (`@img/sharp-win32-x64`, Apache-2.0 AND LGPL-3.0-or-later, optional platform binary pulled by Next.js image handling) | 0                                                            |

Every direct dependency is MIT, BSD, Apache-2.0 or MPL-2.0 except `psycopg`
(LGPL-3.0, used unmodified as a library, already recorded in
[`DATA_SOURCES.md` §8](../licensing/DATA_SOURCES.md)). One transitive Node
package is CC-BY-4.0 (browser-support data). PostGIS (GPL-2.0-or-later) runs as
a database extension and is not distributed with this code.

**Unresolved legal question, not an engineering finding:** whether LGPL
components affect the founder's choice of licence for PathAble itself. Nothing
here changes the obligations already documented; it is listed so the licence
decision is made with the inventory in view.

## 4. Attribution

| Surface                               | OpenStreetMap (ODbL 1.0)                                                                                                          | NRCan HRDEM (Open Government Licence – Canada)                                                                                                           |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| README                                | Present                                                                                                                           | **Added on this branch**                                                                                                                                 |
| `docs/licensing/DATA_SOURCES.md`      | Present, with the share-alike consequence stated                                                                                  | Present, with the exact statement required                                                                                                               |
| Rendered map                          | MapLibre attribution control, non-compact, always visible                                                                         | n/a (tiles carry no elevation)                                                                                                                           |
| Rendered route panel                  | Present (`dataset.attribution` shown with the checksum)                                                                           | **Added on this branch**: shown whenever the response carries `elevation_attribution`                                                                    |
| Every route response                  | `dataset.attribution`                                                                                                             | **Added on this branch**: `dataset.elevation_attribution`, set from the elevation sources stored on the dataset's nodes, null when there is no elevation |
| Generated evidence (`docs/evidence/`) | Screenshots show the map credit; README **now states** the JSON files are ODbL-derived                                            | **Added on this branch** to the evidence README                                                                                                          |
| Geocoding responses                   | Nominatim credit returned with every result                                                                                       | n/a                                                                                                                                                      |
| Future deployment output              | Both credits travel inside the API response, so any client that renders a route holds them; no deployment-specific work is needed | same                                                                                                                                                     |

Verified by rendering: the committed screenshot of the real application shows
the map credit bottom-right and the pilot-panel credit bottom-left; the
frontend unit tests assert both credits (14 page tests, 3 new route-panel
tests), and a PostGIS integration test applies elevation labelled with HRDEM's
source name and asserts the licence statement comes back in the response.

## 5. Dependabot pull requests

Seventeen were open at assessment (the audit counted fifteen; two more arrived
on 2026-09-07). None is bulk-merged here.

| PR  | Update                                                      | Last CI on the PR              | Disposition                                                                                                 |
| --- | ----------------------------------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| #5  | alembic 1.19.0 → 1.19.1 (lock only)                         | 16/16 green                    | Merge now                                                                                                   |
| #17 | next, eslint-config-next 16.3.0 → 16.3.1                    | 16/16 green                    | Merge now                                                                                                   |
| #23 | uvicorn range widened to <0.53                              | 16/16 green                    | Merge now                                                                                                   |
| #29 | @types/react-dom 19.2.4 → 19.2.5                            | 16/16 green                    | Merge now                                                                                                   |
| #30 | @vitejs/plugin-react 6.0.5 → 6.1.1                          | 16/16 green                    | Merge now                                                                                                   |
| #34 | types-networkx stub bump                                    | 16/16 green                    | Merge now                                                                                                   |
| #35 | astral-sh/uv image 0.12.1 → 0.12.10                         | 16/16 green                    | Merge now                                                                                                   |
| #37 | zod 4.4.3 → 4.5.4                                           | 16/16 green                    | Merge now                                                                                                   |
| #38 | @types/node 26.1.2 → 26.4.1                                 | 16/16 green                    | Merge now (supersedes the closed #31)                                                                       |
| #39 | pydantic 2.13.4 → 2.13.5, pydantic-settings 2.14.2 → 2.15.0 | 16/16 green                    | Merge now (supersedes the closed #3)                                                                        |
| #36 | maplibre-gl 6.1.0 → 6.7.0                                   | 16/16 green                    | Not release-blocking; merge after a manual look at the map (rendering library, six minor releases)          |
| #12 | astral-sh/setup-uv action 9.0.0 → 10.0.1                    | 2 failures on 2026-08-17       | Requires review: a major action bump; re-run CI, it may pass now                                            |
| #16 | httpx2 2.9→2.12, mypy 1.20→**2.3**, ruff 0.14→**0.16**      | 1 failure (backend lint/types) | Requires breaking-change review: mypy 2 and ruff 0.16 change rules; new findings need fixing, not silencing |
| #19 | prettier 3.6→3.9, eslint 9→**10**, typescript 5.9→**7.0**   | 7 failures                     | Requires breaking-change review: two majors; TypeScript 7 is a different compiler                           |
| #33 | testing group, 6 updates                                    | 16/16 failed (billing outage)  | Superseded or close later: its failures are the account outage, not the code; Dependabot will rebase        |
| #2  | node base image 22 → **26**                                 | 2 failures (image scan, build) | Requires breaking-change review: a Node major in the runtime image                                          |
| #6  | python base image 3.13 → **3.14**                           | 2 failures (image scan, build) | Requires breaking-change review: the image built and tested on 3.13; `pyproject` should move first          |

## 6. Remediations on this branch

1. **Elevation attribution reaches the user.** The Open Government Licence –
   Canada statement is required on every surface showing a derived gradient.
   It existed only in documentation and CLI output. The route response now
   carries `dataset.elevation_attribution`, resolved from the elevation
   sources actually stored on the dataset's nodes (null when none), the route
   panel shows it, and README and the evidence README state it. Tested at the
   unit, PostGIS-integration and component level; contracts regenerated and
   drift-checked.
2. **Evidence README** states that its map-derived JSON is ODbL-derived data.
3. **`SECURITY.md`** no longer says the project is in Phase 0.
4. **`pyproject.toml`** `Repository` URL pointed at an organisation that does
   not exist; it now names this repository.
5. **`LOCAL_SETUP.md`** explains the thirty-second database connections seen
   when `localhost` resolves to IPv6 first under Docker Desktop, which made the
   integration suite appear to hang during this gate. Environment, not code.

## 7. Founder decisions before publication

1. **Choose a licence**, or decide the code stays all-rights-reserved while
   public. This is the blocker. See `LICENSING.md`, which also lists the
   derived-database (ODbL) consequence and contributor terms.
2. **Commit identity.** 75 commits carry the maintainer's personal email
   address. Publishing a repository publishes its history; a GitHub
   `noreply` address for future commits is a setting, but changing past
   commits is a history rewrite, which this gate does not perform.
3. **Evidence data licence.** The route, coverage and geometry JSON in
   `docs/evidence/` are small OSM-derived extracts. They are now labelled ODbL;
   whether to keep them in a public repository under the project's eventual
   licence is a legal question, not an engineering one.
4. **Free tile service.** OpenFreeMap is the configured style and is not
   approved for production; a public repository is fine, a public deployment
   is a separate decision (ADR 0005).

## 8. Local verification, branch head

| Gate                                                    | Result                                |
| ------------------------------------------------------- | ------------------------------------- |
| gitleaks history (all refs) and tree, after remediation | 0 findings                            |
| `ruff format --check`, `ruff check`, `mypy src tests`   | clean                                 |
| Backend unit suite                                      | 575 passed, 1 skipped (Windows-only)  |
| Backend PostGIS integration suite                       | 91 passed                             |
| `pip-audit --strict`, `pnpm audit`                      | no known vulnerabilities              |
| Prettier, ESLint, TypeScript (`tsc --noEmit`)           | clean                                 |
| Frontend unit suite (Vitest)                            | 200 passed                            |
| Contract drift check                                    | generated contracts match the schemas |
| Frontend production build                               | ok                                    |
| Playwright end-to-end and accessibility suite           | 80 passed                             |
| `docker compose config`                                 | valid                                 |
| Container image builds and Trivy scan                   | not run locally; CI job               |

## 9. Continuous integration

GitHub Actions had been refusing to start jobs since at least 2026-08-31
("recent account payments have failed"). On 2026-09-07 runs started again:
the scheduled `Security` workflow on `main` succeeded, and the six Dependabot
pull requests opened that morning each received sixteen green checks. This
branch's own result is whatever its pull request shows; nothing here is
described as green until a run on this branch has actually completed.

## 10. How to re-run this gate

```bash
# History, every ref, redacted; the report goes outside the repository.
docker run --rm -v "$PWD:/repo:ro" -v "$HOME/gitleaks:/out" -w /repo \
  zricethezav/gitleaks:v8.30.1 git --no-banner --redact \
  --log-opts="--all --full-history" --report-format json --report-path /out/history.json /repo

# Dependencies
cd services/api && uv export --frozen --no-emit-project --no-hashes --all-groups -o requirements-audit.txt \
  && uv run --with pip-audit pip-audit -r requirements-audit.txt --strict
pnpm audit
uv run --with pip-licenses pip-licenses --format=markdown    # Python licence inventory
pnpm licenses list                                            # Node licence inventory

# Attribution and fail-closed configuration
uv run pytest tests/unit/test_config.py tests/unit/test_elevation_providers.py
uv run pytest tests/integration/test_routing_api.py          # needs DATABASE_URL
pnpm --filter @pathable/web test:unit
```
