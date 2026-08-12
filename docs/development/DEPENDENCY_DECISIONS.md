# Dependency decisions

Records for dependency choices that are material enough to need justification —
usually because a reviewer would reasonably ask "why is _that_ in here?".

Routine additions do not belong here. Anything that replaces a well-known package
with a less familiar one, pins away from `latest`, or carries supply-chain risk
does.

---

## 2026-08-05 — `httpx` → `httpx2` (test client)

**Status:** Accepted · dev dependency only · verified 2026-08-05

### Problem

Starlette 1.3.1 raises `StarletteDeprecationWarning` when `starlette.testclient`
is used with `httpx` 0.x:

```
Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
```

The backend test suite runs with `filterwarnings = ["error"]`, so this is not a
cosmetic warning — it fails collection outright. `TestClient` is how every
backend HTTP test is written, so the suite could not run at all.

During P0-A01 this was resolved by swapping to `httpx2` without investigating the
package. A reviewer correctly flagged that: adopting an unfamiliar dependency to
silence a warning is exactly how a supply-chain problem enters a project.

### Verification performed

| Question                   | Finding                                                                                                                  |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Who publishes it?          | PyPI author **Tom Christie** (`tom@tomchristie.com`) — the original author of httpx, Starlette and Django REST Framework |
| Who maintains it?          | **Pydantic Services Inc.** (`engineering@pydantic.dev`)                                                                  |
| Source                     | `github.com/pydantic/httpx2` — not a fork, not archived                                                                  |
| Repository health          | 862 stars, 48 forks, last push 2026-08-05 (same day as this check)                                                       |
| Licence                    | BSD-3-Clause — same as `httpx`                                                                                           |
| Release history            | 13 releases; first 2026-05-11, latest 2.9.1 on 2026-07-24                                                                |
| Does Starlette support it? | **Yes, officially.** Starlette 1.3.1's `full` extra declares `httpx2>=2.0.0` alongside `httpx<0.29.0,>=0.27.0`           |
| Is it a typosquat?         | No. Verified publisher identity, repository, and Starlette's own dependency metadata                                     |

`httpx2` is the official successor to `httpx`, developed by the same author and
now maintained by Pydantic. Starlette's deprecation warning points at it by name.

### Options considered

1. **Adopt `httpx2`** _(chosen)_ — follows the framework's explicit guidance;
   same lineage, same licence, actively maintained.
2. **Keep `httpx` and add a targeted `filterwarnings` ignore.** Viable, and it
   keeps a very widely used package. Rejected because it means knowingly building
   on a path Starlette has announced it is removing, and because a suppressed
   deprecation tends to stay suppressed until it becomes a hard break.
3. **Pin `starlette < 1.3`.** Rejected — pins the whole application to an older
   framework to avoid a test-only issue, which inverts the cost.
4. **Drop `TestClient` for raw ASGI transport calls.** Rejected — loses lifespan
   handling and would mean rewriting every backend HTTP test to work around a
   dependency question.

### Decision

Keep `httpx2`, pinned `>=2.9.1,<3.0.0`, in the **dev dependency group only**.

The blast radius is deliberately small: `httpx2` is not a runtime dependency,
ships in no container image, and reaches no production path. If it were ever
compromised or abandoned, the damage is confined to the test suite, and option 2
above remains available as a fallback.

### Residual risk

The package is young — first released 2026-05-11, roughly three months old at the
time of writing. A young package has had less time to accumulate scrutiny.

Mitigated by: publisher identity verified, dev-scope only, pinned below the next
major, covered by `pip-audit` on every PR and weekly, and tracked by Dependabot.

**Review trigger:** if `httpx2` stops receiving releases for two quarters, or if
Starlette changes its recommendation, revisit and consider option 2.
