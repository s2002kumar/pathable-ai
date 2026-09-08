# Licensing status

## The policy, in one paragraph

**PathAble AI's source code is © Sandeep Kumar. All rights reserved.** The
repository is intended to become **source-visible** — readable by anyone who
opens it — but that is not a grant of any right to use, copy, modify or
redistribute the code. **PathAble is not open source**, and must not be
described as open source, MIT, Apache-2.0, or "free to use" in the README, a
presentation, a CV, or a pitch. Being able to read something is not permission
to reuse it.

The data PathAble is built on is licensed separately and generously. Those two
things are deliberately kept apart, and the rest of this document is mostly
about not confusing them.

The copyright holder is named as **Sandeep Kumar**, the identity every commit in
this repository is authored under and the owner of the GitHub account that hosts
it. If a different person or legal entity should hold the copyright, that is a
correction for the founder to make; nothing here should be treated as
establishing it.

> **Status.** The repository is **private today.** Public visibility is a
> separate, deliberate step, planned as its own release gate. Publishing this
> policy does not publish the repository.

---

## 1. The code: all rights reserved

There is no `LICENSE` file, and that is the decision rather than an omission.
Under default copyright law, absent a licence, all rights are reserved: nobody
other than the copyright holder may copy, modify, redistribute or build on this
code, whether or not they can see it.

What that does and does not mean:

| Question                                                  | Answer                                                                             |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| May somebody read the code once the repository is public? | Yes. That is the point of source-visible.                                          |
| May somebody copy it into their own project?              | No.                                                                                |
| May somebody run it, fork it, or deploy it?               | No, beyond what GitHub's own terms permit for viewing and forking on the platform. |
| May a recruiter or reviewer read it to assess the work?   | Yes. That is why it becomes visible.                                               |
| Is this "source available"?                               | Yes, in the ordinary sense. It is **not** an OSI-approved open-source licence.     |
| Can this change later?                                    | Yes — in the permissive direction. Going the other way is effectively impossible.  |

**Why not simply pick a permissive licence.** Publishing under MIT or Apache-2.0
is a one-way door: everyone who obtains the code under those terms keeps those
rights permanently, and re-licensing only affects future copies. All rights
reserved keeps that door open. It is the reversible choice, taken deliberately,
and it costs nothing that this project currently needs.

**Contributions.** There is one contributor. If that ever changes, contributor
terms (a CLA or a DCO sign-off) must be settled **before** the second person
commits; retroactive agreement is difficult and sometimes impossible.

---

## 2. The data: not ours, and licensed on its own terms

This is the distinction that matters most, and it runs the opposite way to the
code. The code is restrictive and ours. The data is permissive and other
people's, and it comes with obligations that all-rights-reserved on the code
does nothing to alter.

| Layer                                                            | Licence                                                                               | What it obliges                                                      |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Source code in this repository                                   | © Sandeep Kumar, all rights reserved                                                 | Nothing on us; no rights granted to anyone else                      |
| OpenStreetMap data, and the pedestrian graph derived from it     | [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/)                            | Visible attribution; share-alike on a publicly used derived database |
| Elevation from NRCan HRDEM / CanElevation                        | Open Government Licence – Canada                                                      | The OGL statement wherever a derived gradient is shown               |
| Measurement files in [`docs/evidence/`](docs/evidence/README.md) | ODbL-derived content, attributed in that directory's README                           | Attribution travels with them; they stay public and clearly labelled |
| Dependencies                                                     | Their own — see [`docs/licensing/DATA_SOURCES.md`](docs/licensing/DATA_SOURCES.md) §8 | Their own notices                                                    |

### The evidence files stay public, and stay labelled

[`docs/evidence/`](docs/evidence/README.md) holds route comparisons, coverage
counts, a geometry inspection and a graph-load benchmark, all computed from an
OpenStreetMap extract. They are **OSM-derived data, not PathAble's own work**,
and [`docs/evidence/README.md`](docs/evidence/README.md) says so at the top with
the ODbL and Open Government Licence credits attached. Keeping them visible is
the decision; keeping the two licences visibly separate is the condition.

### The share-alike consequence, stated plainly

The pedestrian graph PathAble builds is a **Derivative Database** under ODbL
§4.4. If PathAble is ever _publicly deployed_, that graph must be offered under
ODbL. This is independent of the code being all rights reserved: ODbL attaches
to the database, copyright attaches to the source, and neither overrides the
other. Treat it as a contribution back rather than an obligation to route
around. See [`docs/licensing/DATA_SOURCES.md`](docs/licensing/DATA_SOURCES.md)
§2 for the full analysis.

---

## 3. What was decided, and what is still open

**Decided.**

1. The code is source-visible and all rights reserved. Not open source.
2. Git history is preserved as it stands, including historical commit email
   addresses. No history rewrite. Future commits use the GitHub-provided
   `users.noreply.github.com` address, configured for this repository only.
3. The OSM-derived evidence files stay public, with ODbL and OGL attribution
   kept clearly separate from the code's copyright.
4. The repository stays private until its own dedicated release gate.

**Still open, and genuinely a founder decision.**

- Whether to move to a permissive or source-available licence later, and which.
- Contributor terms, needed before a second contributor.
- Whether a public deployment happens at all, which is what triggers the ODbL
  derived-database obligation in §2.

---

## 4. Wording that is accurate

Use:

- "Source-visible. © Sandeep Kumar, all rights reserved."
- "Built on OpenStreetMap data under ODbL 1.0."
- "Not open source."

Do not use:

- "Open source", "MIT-licensed", "Apache-licensed", "free to use", "public
  domain", or any phrasing implying a right to reuse the code.
