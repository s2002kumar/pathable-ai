# Testing

## The four suites

| Suite               | Command                                 | Runtime deps | What it proves                                                            |
| ------------------- | --------------------------------------- | ------------ | ------------------------------------------------------------------------- |
| Backend unit        | `uv run pytest tests/unit`              | none         | Config validation, correlation, error sanitisation, health logic          |
| Backend integration | `uv run pytest tests/integration`       | **PostGIS**  | Migrations from empty, PostGIS present, readiness against a real database |
| Frontend unit       | `pnpm --filter @pathable/web test:unit` | none         | Config parsing, status probe, map state machine, component behaviour      |
| End-to-end          | `pnpm --filter @pathable/web test:e2e`  | Chromium     | The real page in a real browser, plus accessibility                       |

From the root: `pnpm test` (unit only), `pnpm test:integration`, `pnpm test:e2e`,
or `pnpm check` for everything that does not need Docker.

---

## Two hard rules

### 1. No test may depend on public tile availability

Browser tests use `apps/web/public/map-styles/offline-test-style.json`: one
background layer, **no sources**. MapLibre reaches its `load` event with zero
network requests. The suite therefore passes offline, in CI, and on a day when a
tile provider is down.

Failing tests should tell you your code is broken. A test that fails because
someone else's server is slow trains people to re-run until green, which destroys
the value of the whole suite.

### 2. No test may require a running backend

Playwright points `NEXT_PUBLIC_API_BASE_URL` at `http://127.0.0.1:9` — a closed
port. So the default state under test is a genuinely unreachable API, and tests
needing a specific backend state stub it at the network layer:

```ts
await stubHealthyApi(page); // 200 ready
await stubDegradedApi(page); // 503 not_ready
// no stub                     -> real connection failure
```

Full-stack behaviour is verified separately with `docker compose up`.

---

## Backend

### Unit

No database, no network. Coverage floor **85%** on `src/pathable_api`, enforced in
CI with `--cov-fail-under=85`.

Notable coverage:

- **Configuration** — port and coordinate bounds, CORS origin parsing and
  trailing-slash normalisation, `postgresql://` → `postgresql+psycopg://`,
  production hardening (missing `DATABASE_URL`, wildcard origin, non-JSON logs),
  and that _all_ production problems are reported at once.
- **Credential safety** — `safe_database_target()` never emits a password.
- **Correlation** — generation, adoption of a valid inbound id, replacement of a
  malformed one (including newline-injection attempts), no leakage between
  requests.
- **Error handling** — a deliberately leaky exception message containing a DSN
  and password never appears in the response; validation errors do not echo the
  rejected input.
- **Liveness independence** — succeeds with no database configured _and_ with a
  configured but unreachable one.
- **Dependency probes** — healthy, PostGIS missing, unreachable, and timeout, all
  against hand-built stand-ins so the failure paths are fast and deterministic.

Settings in tests are always built with `_env_file=None`, so a developer's local
`.env` can never change an outcome.

### Integration

Requires a live PostgreSQL/PostGIS. Skips with an explanatory message if
`DATABASE_URL` is unset, rather than failing.

**Every test runs against a throwaway database**, created and dropped per test.
That is what makes "migrations work from an empty database" a real assertion
rather than a statement about whatever state your database happened to be in.

```
create pathable_test_<random>
  → alembic upgrade head (via -x db_url=..., never the ambient DATABASE_URL)
  → assertions
  → drop database
```

Coverage: PostGIS absent before migration, present after; the revision is
recorded in `alembic_version`; upgrade is idempotent (the container entrypoint
migrates on every start); `ST_Distance` genuinely works; downgrade removes the
extension and clears the version; upgrade → downgrade → upgrade round-trips.
Readiness returns 200 against a migrated database, 503 against an un-migrated one
(reachable but unusable), and 503 without leaking the connection string.

---

## Frontend

Vitest + React Testing Library, jsdom. Coverage floor **80%** on statements,
branches, functions and lines.

`src/test/setup.ts` makes `globalThis.fetch` **throw by default**. A test that
forgets to stub the network fails loudly instead of quietly reaching the real
internet and becoming flaky.

Notable coverage: public configuration validation (every out-of-range coordinate,
zoom and URL, plus the "reports all problems at once" behaviour and that the
region is not hard-coded to Waterloo); the status probe including timeout versus
refused-connection; the map state machine — unsupported, ready, initialisation
error, a tile error _after_ ready not downgrading the map, the init timeout, and
cleanup on unmount; and the shell — development disclosure, pilot description,
accessible map name, healthy and unavailable API states, and the assertion that
**no routing controls exist**.

### Coverage exclusions

| Excluded                       | Reason                                                                                                                                                           |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `**/generated/**`              | Generated from the backend OpenAPI document; not authored here                                                                                                   |
| `src/test/**`, `*.test.*`      | Test scaffolding                                                                                                                                                 |
| `**/*.d.ts`, `src/**/types.ts` | Type-only; compiles to nothing                                                                                                                                   |
| `src/app/layout.tsx`           | A static `<html>` shell plus metadata literals. Any test would restate the literal, and rendering a root `<html>` in jsdom tests the framework, not this project |

Nothing with a branch or a behaviour is excluded.

---

## End-to-end

Playwright, two projects: `desktop-chromium` (1440×900) and `mobile-chromium`
(Pixel 7).

Headless Chromium has no GPU, so both launch with
`--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader` to provide
the WebGL 2 context MapLibre needs. Without it the suite would only ever exercise
the unsupported-browser fallback.

Coverage: page load and product identity; the Phase 0 disclosure; the written
pilot description; attribution both in the panel and as a MapLibre control
positioned inside the map frame; map initialisation reaching `ready` against the
offline style; the map's accessible name; **absence** of routing controls;
keyboard focus visibility and the skip link; no horizontal overflow; backend
online / degraded / offline; the page remaining fully usable with the backend
down; map loading and failure states; and an axe scan.

Screenshots land in `apps/web/artifacts/screenshots/` (git-ignored, uploaded by
CI):

```
{project}-application.png
{project}-map-loading.png
{project}-map-failure.png
```

They are evidence, not visual-regression baselines. Committing them would mean
committing a binary that changes on every font or renderer update, and reviewing
diffs nobody can read. If visual regression is wanted later, it needs a dedicated
tool and pinned rendering.

### Determinism

Two techniques worth knowing about:

- **`data-map-state`.** Tests wait on an attribute, not on canvas pixels.
- **A gated route, not a timed delay.** `holdMapStyle(page)` blocks the style
  response until the test releases it. A `setTimeout(3000)` looked fine and then
  failed intermittently on a loaded machine, because `page.goto` could consume
  the whole delay before the assertion ran.

Both flaky failures found during Phase 0 were fixed at the source rather than
papered over with retries.

---

## Manual real-basemap verification

**CI deliberately cannot catch a broken basemap.** Every automated suite uses the
source-less offline style so that a green build never depends on a third-party
tile server. That style needs no tile worker and fires `load` regardless of
whether tiles would render — which is precisely how KI-1 stayed hidden while the
map drew nothing at all.

So the real map is verified by hand, in a real browser, before any release:

```bash
docker compose up -d db          # or any real PostGIS
pnpm map:evidence                 # builds with the real style and screenshots it
```

Then open the app in an ordinary browser and confirm:

- [ ] Streets, water, parks and labels are drawn; Waterloo is recognisable
- [ ] The network panel shows `.pbf` vector-tile requests returning 200
- [ ] Attribution is visible on the map
- [ ] Zoom buttons work, and dragging pans the map
- [ ] Resizing the window keeps the map filling its frame
- [ ] The console has no unexpected errors

`pnpm map:evidence` reports tile counts, map state, attribution and console
errors, and writes `apps/web/artifacts/screenshots/real-basemap-*.png`. It is a
manual aid, never a CI job.

> Headless Chromium with SwiftShader is **not** sufficient for this check. It can
> render the offline style perfectly while a real vector basemap fails.

## Accessibility testing

`@axe-core/playwright` scans the shell in both the ready and map-failure states,
tagged `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`. Serious and critical
violations fail the build; the failure message names the offending **element**,
not just the rule.

MapLibre's own control chrome (`.maplibregl-control-container`) is excluded — it
is third-party markup this project does not author, and the scan should report
what the team can fix.

### What automated checks do not prove

**axe catches roughly the machine-detectable minority of accessibility problems.
Passing it is a floor, not a claim of accessibility.**

It cannot tell you whether the pilot description is genuinely useful to someone
who cannot see the map, whether focus order is logical, whether an accessible
name is meaningful rather than merely present, whether the language is clear, or
whether the product works with a real screen reader.

Before any public release, PathAble requires manual keyboard and screen-reader
review, and evaluation with disabled users. For a product whose purpose is
accessibility, shipping on an automated pass alone would be indefensible.

---

## Writing tests here

Test the behaviour, not the implementation. Assert what a user or caller
observes, so a refactor does not rewrite the suite.

Test the failure paths — in this codebase they are the interesting ones. Database
unreachable, PostGIS missing, WebGL absent, style 404, invalid configuration:
that is what people will actually hit.

Never write a test purely to move a coverage number. It costs maintenance, proves
nothing, and makes the number a lie.

Explain non-obvious assertions with a comment saying _why_ the behaviour matters,
not what the code does.

---

## CI

`.github/workflows/ci.yml` runs, in parallel: backend format/lint/types, backend
unit tests with coverage, backend integration tests against a PostGIS service
container, frontend format/lint/types, frontend unit tests with coverage,
contract drift, the production build, Playwright + axe, and Docker image builds
including a check that no `.env` is baked into the API image.

`.github/workflows/security.yml` runs `pip-audit`, `pnpm audit`, gitleaks over
full history, and environment-file hygiene checks — on every PR and weekly.

Failure artefacts (Playwright report, traces, screenshots, coverage) are uploaded
and retained for 7 days.
