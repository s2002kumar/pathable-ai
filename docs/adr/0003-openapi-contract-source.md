# ADR 0003 — Backend Pydantic schemas are the contract source of truth

**Status:** Accepted · 2026-08-05 · Phase 0 (P0-A01)

## Context

The frontend needs types for API responses. Three ways to get them:

1. Hand-write TypeScript interfaces mirroring the Python models.
2. Write a schema in a neutral language and generate both sides.
3. Generate TypeScript from the backend's OpenAPI document.

Option 1 is what most projects do, and it fails the same way every time: someone
renames a field, the Python side is updated, the TypeScript interface still
compiles, and the bug surfaces at runtime as `undefined`. The types stop being a
guarantee and become a hopeful comment.

Option 2 (Protobuf, Smithy, TypeSpec) is genuinely rigorous, but it introduces a
third language, a third build step, and a schema that must be kept in sync with
the FastAPI route signatures anyway.

Option 3 uses something we get for free: FastAPI already derives a complete
OpenAPI document from the Pydantic models used in route signatures. The models
are not a description of the contract — they are the code that enforces it at
runtime.

## Decision

**Pydantic response models in `services/api/src/pathable_api/schemas/` are the
single source of truth.**

```
Pydantic models → app.openapi() → openapi.json → openapi-typescript → api.ts
```

Both `openapi.json` and `api.ts` are **committed**, so a clean checkout type-checks
without running Python. `pnpm contracts:check` regenerates both into a temporary
directory and compares bytes; CI fails on any difference.

### Generator: `openapi-typescript`

Chosen over `orval`, `openapi-generator` and `hey-api`:

| Candidate                           | Why not                                                                                          |
| ----------------------------------- | ------------------------------------------------------------------------------------------------ |
| `orval`                             | Generates a runtime client and wants an HTTP library opinion. Phase 0 needs types, not a client. |
| `openapi-generator` (OpenAPI Tools) | Java toolchain in CI; verbose output; heavier than the problem.                                  |
| `hey-api`                           | Capable, but again a runtime client we do not need yet.                                          |
| **`openapi-typescript`**            | **Emits pure types. Zero runtime dependency. Deterministic. One file.**                          |

Because the output is types only, `@pathable/contracts` erases entirely at
compile time — the frontend imports it with `import type` and ships no extra
bytes.

### Determinism

The drift check is worthless if generation is not byte-stable. Therefore
`openapi_export.py` builds the app from **fixed settings with `_env_file=None`**,
not the ambient environment, and serialises with sorted keys, fixed indentation
and a trailing newline. The OpenAPI `info.version` comes from the package
constant rather than the configurable `APP_VERSION`, so a deployment variable
cannot change the contract document.

`operationId` is set explicitly (`getLiveness`, `getReadiness`). FastAPI's
auto-generated ids embed the route path and function name, so any refactor would
churn the generated client names.

## Consequences

**Positive**

- Renaming a backend field breaks the frontend build. That is the entire point.
- Zero runtime cost on the client.
- One place to change a response shape.
- The error envelope is part of the contract: `ApiErrorResponse` is declared on
  the router, so the frontend has a typed failure path as well as a typed success
  path.

**Negative**

- Regenerating requires a working Python environment, so a frontend-only
  contributor needs `uv` to run `contracts:check`. Mitigated by committing the
  generated files: only someone changing the backend needs to regenerate.
- Generated types follow OpenAPI's structure (`components['schemas']['X']`).
  Mitigated by hand-written aliases in `packages/contracts/src/index.ts`.
- A stale commit is possible if someone bypasses CI. Accepted: CI is the gate.

**Reversibility.** High. The generator can be swapped by rewriting one function
in `scripts/contracts.mjs`; the OpenAPI document is the stable interface.

## Alternatives considered

**Hand-written TypeScript interfaces.** Rejected: the failure mode is silent, and
it is precisely the failure mode a type system is supposed to prevent.

**Runtime validation on the client (zod schemas generated from OpenAPI).**
Attractive, and likely correct later for the routing responses. Rejected for
Phase 0 because the only consumed endpoint is readiness, whose narrowing is a
nine-line type guard, and adding generated runtime validators now would ship
bytes to validate a health check.

**Backend generated from a TypeScript-first schema.** Inverts the dependency so
that the language enforcing the contract at runtime is downstream of the one that
does not. Rejected.
