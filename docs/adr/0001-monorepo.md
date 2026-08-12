# ADR 0001 — Single monorepo for web, API and contracts

**Status:** Accepted · 2026-08-05 · Phase 0 (P0-A01)

## Context

PathAble has three deliverables that change together: a Next.js frontend, a
FastAPI backend, and the API contract binding them. The team is one person with
exam commitments.

The question is whether these live in one repository or several.

Separate repositories force the contract to travel as a published artefact — a
versioned npm package, or a copied OpenAPI file. Every backend response change
becomes: change backend, publish contract, bump frontend, verify. That is
reasonable at organisational scale, where teams deploy independently. Here it
would be pure overhead, and the predictable failure is a contract that drifts
because keeping it in sync is tedious.

A monorepo makes the drift check mechanical: regenerate, compare, fail the build.
The cost is that the repository contains two toolchains (pnpm and uv) and that
CI must know which parts to run.

## Decision

One repository, `pathable-ai`, containing:

```
apps/web              pnpm workspace member
services/api          uv project
packages/contracts    pnpm workspace member, generated
```

pnpm workspaces manage the JavaScript side; uv manages Python. They are not
unified under a single orchestrator. The root `package.json` provides the
cross-cutting commands, delegating to `pnpm --filter` and `uv --directory`.

No Nx, Turborepo, Bazel or Lerna. A build graph is worth its configuration cost
when builds are slow enough to need caching and parallelism. Here the full
check runs in a couple of minutes. Adding an orchestration framework now would
add a layer to debug for no measured benefit — and would need to be justified by
data we do not have.

## Consequences

**Positive**

- The contract drift check is a build step, not a process.
- One clone, one `pnpm bootstrap`, one branch, one PR for a full-stack change.
- CI runs frontend, backend and contract checks against a single commit.
- Refactoring across the boundary is atomic.

**Negative**

- Contributors install both toolchains even to touch one side. Mitigated by
  `pnpm bootstrap` and by scripts that resolve `uv` themselves.
- CI does slightly more work than strictly necessary on a single-sided change.
  Acceptable at this size; job-level path filters can be added when it hurts.
- Git history mixes concerns. Mitigated by Conventional Commit scopes.

**Reversibility.** Splitting later is straightforward — `git filter-repo` per
directory, then publish `@pathable/contracts` to a registry. Nothing in the code
assumes co-location beyond the generation scripts' relative paths.

## Alternatives considered

**Three repositories with a published contracts package.** Correct at scale,
premature here. Every cross-cutting change becomes a multi-repo dance, and
contract drift becomes a human responsibility rather than a build failure.

**Two repositories, frontend and backend, with a copied OpenAPI file.** The worst
option: all the coordination cost of splitting, plus a contract that is copied by
hand and will silently rot.

**Monorepo with Turborepo or Nx.** Real benefits — task caching, affected-project
detection — that only materialise with more packages and slower builds than exist
here. Revisit when `pnpm check` becomes slow enough to measure as a problem.
