# Contributing to PathAble AI

## What this project is trying to be

PathAble AI will tell people whether a route is usable given how they move. If it
is wrong, someone can end up at an unramped kerb, on a route with no curb cut, or
stuck. That shapes how we build:

- **Never imply a capability that does not exist.** A control that looks live but
  does nothing is worse than no control.
- **Never state a metric that was not measured.** Not in the UI, not in a PR, not
  in the README.
- **Accessibility is a requirement, not a phase.** This is an accessibility
  product; an inaccessible interface is a broken product.
- **Absence of data is not evidence of accessibility.** "No barrier recorded" and
  "no barrier" are different claims and must stay distinguishable.

## Getting set up

See [Local setup](docs/development/LOCAL_SETUP.md). Short version:

```bash
cp .env.example .env
pnpm bootstrap
pnpm dev
```

## Before you open a pull request

```bash
pnpm check            # format, lint, types, unit tests, contracts, build
pnpm test:e2e         # if you touched the frontend
pnpm test:integration # if you touched the database (needs Docker)
```

`pnpm check` is the same gate CI runs, minus the parts that need Docker.

## Branches and commits

Branch from `main`: `feature/<slug>`, `fix/<slug>`, `docs/<slug>`,
`chore/<slug>`.

Commits follow Conventional Commits:

```
feat(web): add mobility profile selector
fix(api): reject database URLs without a database name
docs(adr): record the OpenAPI contract decision
build: pin the PostGIS image to 17-3.5
test(api): cover the readiness timeout path
```

Scopes in use: `web`, `api`, `db`, `contracts`, `infra`, `docs`, `ci`.

Keep commits logically separate. One commit that adds a feature, its tests and
its documentation is good; one commit containing four unrelated changes is not.

## Code standards

### Everywhere

- No `any`, no blanket `# type: ignore`, no blanket lint disables. A narrow,
  commented exception is fine; a broad one is not.
- No skipped tests without a comment explaining what unblocks them.
- No swallowed exceptions. If you catch, either handle it or log it.
- Comments explain _why_. The code already says _what_.

### Python (`services/api`)

Ruff formats and lints; mypy runs in strict mode. Response models live in
`schemas/` and are the contract source of truth — after changing one, run
`pnpm contracts:generate` and commit the regenerated files.

Never put a connection string, credential or driver message into an HTTP
response. `Settings.safe_database_target()` exists for exactly this.

### TypeScript (`apps/web`)

Strict mode with `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes`.
Never hand-write a type that duplicates an API response — import it from
`@pathable/contracts`.

CSS Modules per component; colours, spacing, radii and shadows come from the
tokens in `src/styles/tokens.css`. A raw hex value in a component is a bug: it
will not follow the dark theme.

### Accessibility

Non-negotiable for any user-facing change:

- Keyboard reachable with a visible focus indicator. Never `outline: none`.
- Interactive and landmark elements have accessible names.
- Colour is never the only carrier of meaning.
- WCAG AA contrast in **both** light and dark themes.
- No horizontal overflow at narrow viewports.
- Touch targets are comfortably tappable.

Run `pnpm test:e2e`, which includes an axe scan. Then check it yourself with a
keyboard — axe catches only a minority of real problems.

## Tests

Every behaviour change needs a test that would fail without it. Tests written
only to move a coverage number are worse than no test: they cost maintenance and
prove nothing.

Test the failure paths. In this codebase the interesting cases are the database
being unreachable, the map failing to initialise, WebGL being absent, and
configuration being wrong — those are what users will actually hit.

## Documentation

- A decision that shapes the architecture gets an ADR in `docs/adr/`.
- New configuration gets an entry in `.env.example` **and** the README table.
- If a change alters what the product can or cannot do, update the Phase 0
  disclosure so it stays true.

## Decisions you should not make alone

Open a discussion first if a change would introduce a cost, need credentials, use
data with unclear licensing, make the repository public, deploy anything, collect
personal data, or make a safety or accessibility guarantee. Everything else:
decide, document the trade-off, and note it in the PR.
