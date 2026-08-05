# Licensing status

## No licence has been selected for this project

PathAble AI is **private, unreleased, and not licensed for redistribution.**

There is deliberately no `LICENSE` file in this repository. Under default
copyright law that means all rights are reserved: nobody other than the copyright
holder may copy, modify, redistribute or use this code.

**This project is not open source.** It should not be described as open source,
nor as Apache-2.0, MIT, or anything else, in the README, in a presentation, on a
CV, or in a pitch, until a licence is actually chosen.

### Why the previous licence was removed

An Apache-2.0 `LICENSE` file was added during the Phase 0 foundation batch
(P0-A01) as a default, without the founder having approved it. Choosing a licence
is not a routine engineering decision:

- It is **effectively irreversible in practice**. Once code is published under a
  permissive licence, anyone who obtained it under those terms keeps those rights
  forever. Re-licensing later only affects future copies, and only if every
  contributor agrees.
- It determines whether others may build commercial products on this work.
- It interacts with the ODbL share-alike obligations that attach to the
  OpenStreetMap-derived data this project will produce (see
  [`docs/licensing/DATA_SOURCES.md`](docs/licensing/DATA_SOURCES.md)).
- If PathAble is ever associated with a university programme, an accelerator, or
  external funding, those relationships can carry their own IP terms.

The licence was therefore removed rather than swapped for a different one. **This
document does not recommend a replacement**; that is the founder's decision.

### What this does not block

Nothing in the current workflow. Private development, GitHub, CI, dependencies
and contributions by the founder all work without a licence. This only matters at
the point of publication.

---

## Decisions the founder needs to make before any public release

These are release-readiness items, not engineering tasks:

1. **Should the repository become public at all?**
2. **If so, under which licence?** The usual axes are whether others may build
   commercial products on it, and whether modifications must be shared back.
3. **Contributor terms.** If anyone else ever commits, decide up front whether a
   CLA or a DCO sign-off is required. Retroactive agreement is difficult and
   sometimes impossible.
4. **Derived-data licence.** The Phase 0.5 pedestrian graph will be a derived
   database under ODbL. If PathAble is publicly deployed, that graph must be
   offered under ODbL — independently of whatever licence covers the source code.
   The two are separate decisions.

Until item 1 and item 2 are settled, the repository stays private and unlicensed.

---

## What is _not_ affected by this

Third-party licensing obligations are unchanged and still apply in full:

- **OpenStreetMap data** is ODbL 1.0 and requires visible attribution. It is
  attributed on the map and in the pilot panel today.
- **Dependency licences** (MapLibre BSD-3, Next.js and React MIT, FastAPI and
  SQLAlchemy MIT/BSD, psycopg 3 LGPL-3.0, PostGIS GPL-2.0-or-later, and the rest)
  are documented in [`docs/licensing/DATA_SOURCES.md`](docs/licensing/DATA_SOURCES.md).
- **Map tile and future geocoding providers** have their own terms, also recorded
  there.

Removing PathAble's own licence changes none of that. Those obligations exist
because of what the project _uses_, not because of how it is licensed.
