# ADR 0009 — Deployment architecture, sized from the measured production envelope

- **Status**: Proposed — awaiting the founder's provider and cost approval
- **Date**: 2026-09-11
- **Related**: [0004 PostGIS and the runtime graph](0004-postgis-and-runtime-graph.md),
  [0005 map and geocoding providers](0005-map-and-geocoding-providers.md),
  [KI-6](../development/KNOWN_ISSUES.md), [production smoke procedure](../deployment/PRODUCTION_SMOKE.md),
  [measurements](../evidence/production-envelope.json)

Nothing has been deployed, purchased or signed up for. This document records
what the production containers actually need, which hosting shapes can and
cannot supply it, and one recommendation with one fallback. The decision
itself — provider, tier, and therefore money — is the founder's.

## Context

PathAble's API holds a city's pedestrian graph in memory: 155,714 nodes and
180,554 segments for the Waterloo pilot, built from PostGIS at startup. That
one fact shapes everything about hosting. An instance is not useful until the
graph is loaded, the graph costs about a gigabyte of resident memory for as
long as the process lives, and every worker process holds its own copy.

Until this card, readiness answered "ready" the moment PostgreSQL was
reachable, and the graph loaded on the first route request. That is fine on a
laptop and wrong behind a load balancer. `GRAPH_PRELOAD_REGIONS` now loads the
configured regions at startup and holds readiness at 503 until they are
routable; the development default stays lazy.

Everything below was measured on the real images, from an empty database, in
an isolated Compose project (`pathable-envelope`) that never touches the
development volume. The procedure is reproducible from
[`docs/deployment/PRODUCTION_SMOKE.md`](../deployment/PRODUCTION_SMOKE.md) and
the raw numbers are in
[`docs/evidence/production-envelope.json`](../evidence/production-envelope.json).

### Machine and conditions

Windows 11 laptop (Intel Core Ultra 7 155H, 16 GB), Docker Desktop 28.4.0 with
Compose 2.39.4, Linux VM with 22 vCPUs and 7.99 GB. **The host had 856 MB of
its 16 GB free when the batch started**, so absolute wall-clock is this
laptop's under pressure and is quoted as a shape, not a service level. Memory
figures are what the Linux cgroup and `/proc` reported inside the container,
which is what a hosting limit is enforced against; they are not affected by
host swapping. Time starts when `compose up` is issued on the host (about a
second of Compose overhead is inside every start-to-\* figure). The Docker VM's
clock was a day adrift from the host, so no container timestamp is subtracted
from a host one.

Dataset `51585450-8ff5-409d-a02e-66d5a3c5e260`, checksum `51e75f78…d2e906` —
the same one every file in `docs/evidence/` describes. PostgreSQL 17.5,
PostGIS 3.5.2, Alembic head `0005_kerb_tiers`.

## What was measured

### Startup, from an empty database

| Step                                                        | Result                                                                                                         |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Migrate from zero to `0005_kerb_tiers`                      | 1 s of Alembic inside a 4.0 s container run; creates 6 tables + PostGIS                                        |
| Migrate again                                               | No-op, 4.2 s wall                                                                                              |
| Migrate with a revision that does not exist                 | Alembic exits non-zero, entrypoint `set -e` ends the container, exit 255, restart loop; liveness never answers |
| Populate the Waterloo rows (31.2 MB logical dump, 5 tables) | 7.2 s restore + 1.1 s `vacuum analyze`; volume 113 MB → 544 MB during load, 190 MB database after              |

### Cold start, one worker, 2 GB limit — three runs, all valid

| Metric                                      |           run 1 |       run 2 |       run 3 |  median |
| ------------------------------------------- | --------------: | ----------: | ----------: | ------: |
| `compose up` → `/health/live` 200 (s)       |            3.66 |        4.08 |        4.07 |    4.07 |
| `compose up` → `/health/ready` 200 (s)      |           18.33 |       18.67 |       19.57 |   18.67 |
| Migration (already at head) (s)             |             1.0 |         1.0 |         1.0 |     1.0 |
| Graph preload, from the readiness body (s)  |           13.47 |       14.60 |       15.08 |   14.60 |
| RSS before graph load (MB)                  |            26.6 |        27.2 |        27.6 |    27.2 |
| RSS peak while loading, 1 s samples (MB)    |         1,023.6 |       995.4 |     1,026.1 | 1,023.6 |
| Sum of per-process VmHWM at ready (MB)      |         1,064.0 |     1,063.9 |     1,064.6 | 1,064.0 |
| RSS at ready (MB)                           |           996.7 |       995.6 |       997.2 |   996.7 |
| RSS after 10 s idle (MB)                    |           997.2 |       995.9 |       997.6 |   997.2 |
| cgroup memory peak / steady (MB)            |     1,024 / 969 | 1,005 / 963 | 1,017 / 964 |       — |
| First route after ready (wheelchair, 366 m) | 134 ms, 59.8 KB |      119 ms |      117 ms |  119 ms |

VmHWM is each process's own lifetime peak and cannot be missed by sampling:
**the true single-worker peak is 1,064 MB**, of which ~997 MB stays resident
for the life of the process. The "two processes" the report counts are the
server and the sampler's own `sh`, which the measurement runs inside the
container and which costs well under a megabyte; the entrypoint `exec`s the
server, so there is no shell wrapper at runtime.

**Restart and shutdown.** `docker restart` returns in 6.9 s and readiness
returns 25.3 s after the restart was issued. `docker stop` completes in 6.2 s
with exit code 0 and the shutdown logged: SIGTERM reaches the exec'd server,
the lifespan runs, the engine is disposed.

### Memory limits, one worker — two cold starts each

| Limit   | Became ready | cgroup peak (MB) | RSS peak (MB) | Headroom at peak | Graph load (s) |
| ------- | ------------ | ---------------: | ------------: | ---------------: | -------------: |
| 1 GB    | 2 / 2        |            1,005 |       1,051.5 |           **6%** |     13.7, 14.2 |
| 1.25 GB | 2 / 2        |            1,040 |       1,058.8 |              19% |     13.1, 36.8 |
| 1.5 GB  | 2 / 2        |            1,012 |       1,082.8 |              34% |     25.6, 24.2 |
| 2 GB    | 3 / 3        |            1,024 |       1,026.1 |              50% |      13.5–15.1 |

A 1 GB limit _survived_ both starts, with the kernel reclaiming page cache
down to a few percent of headroom. That is the case against sizing at the
observed peak: it works on the day it is measured and fails on the day a
second region is added, a burst of large responses is built, or the allocator
fragments. The slower graph loads under 1.25 and 1.5 GB were measured while
the host itself was starved (see conditions); they cannot be attributed to the
limit and are recorded rather than explained.

### Worker count

uvicorn `--workers 2` on the same image, 4 GB limit, two runs:

| Metric                     |   run 1 |   run 2 |
| -------------------------- | ------: | ------: |
| Processes in the container |       5 |       5 |
| `compose up` → ready (s)   |    44.0 |    33.4 |
| RSS peak (MB)              | 2,124.3 | 2,164.5 |
| Sum of VmHWM at ready (MB) | 2,172.3 | 2,173.9 |
| RSS steady (MB)            | 2,057.2 | 2,038.1 |
| cgroup peak (MB)           | 2,082.8 | 2,028.5 |

**The graph is duplicated per worker**: two workers cost 2.04 GB resident and
2.17 GB at peak — 2.04× one worker. Two workers under a 2 GB limit also
survived one start, at a cgroup peak of 2,001.9 MB against 2,048 MB: 2.3%
headroom, which is not a configuration but an accident waiting to happen.

### Route latency and the small concurrency probe

Warm, on this laptop, single worker: the 366 m campus route answers in 67–122
ms (56–60 KB); the 3 km cross-town route in 863–1,351 ms (158 KB). The engine
is CPU-bound Python on one core.

Six requests per client, alternating two journeys and two profiles, after
warming. Every response at every level was HTTP 200 and matched the reference
answer byte-for-byte on distance, segment count and stairway count — zero
errors, zero timeouts, zero mismatches.

| Clients | One worker: req/s, p50, p95 (ms) | Two workers: req/s, p50, p95 (ms) |
| ------: | -------------------------------- | --------------------------------- |
|       1 | 2.02, 445, 974                   | 1.99, 508, 919                    |
|       2 | 2.45, 738, 1,020                 | 2.55, 298, 966                    |
|       4 | 2.74, 1,456, 1,625               | 3.76, 737, 1,621                  |
|       8 | 2.28, 3,459, 3,953               | 4.63, 945, 2,414                  |

One worker saturates one core at about 109% CPU and queues everything behind
it: eight concurrent clients wait three and a half seconds at the median. Two
workers roughly double throughput at eight clients and halve the wait, at the
cost of a second gigabyte. **This is not a load test and says nothing about
user scale.** It says that a single worker serves one person at a time
comfortably, a handful with visible queueing, and that the memory price of a
second worker is exactly one more graph.

### Images and the web tier

| Image | Content size (`docker image inspect`) | Unpacked (`docker image ls`) | User      | Entrypoint / command                           |
| ----- | ------------------------------------: | ---------------------------: | --------- | ---------------------------------------------- |
| API   |                              208.5 MB |                       899 MB | uid 10001 | `api-entrypoint.sh` → `python -m pathable_api` |
| Web   |                               93.1 MB |                       387 MB | uid 10001 | `node apps/web/server.js` (Next.js standalone) |

Neither image carries an environment file, a credential, pip, npm or corepack;
the API's baked environment is `PATH`, Python's own variables and two Python
flags. The web container answers `/api/healthz` and serves the page in 40 ms
with 86 MB resident, the security headers set, and `NEXT_PUBLIC_API_BASE_URL`
baked at build time — so a web image is specific to the API origin it was built
for. CORS from the web origin is allowed; `/docs` is 404 under
`ENVIRONMENT=production`.

### Database

190 MB after load: `graph_edges` 121 MB (76 MB heap, 45 MB indexes),
`graph_nodes` 49 MB (28 / 21), everything else under 8 MB. The volume grew to
544 MB while the rows streamed in (WAL and temporary space), so budget about
3× the resident size for a bootstrap. One API worker opens a pool of 5 with 5
overflow; `max_connections` is 100 by default. The logical backup of the five
map-fact tables is 31.2 MB and restores in 7 s; restore has been exercised
here, into an empty database, once.

## The envelope, stated

| Quantity                              | Measured                       | Sized with 30% headroom | Tier to buy                                   |
| ------------------------------------- | ------------------------------ | ----------------------- | --------------------------------------------- |
| API memory, one worker                | 1,083 MB peak, 997 MB steady   | 1.41 GB                 | **2 GB**                                      |
| API memory, two workers               | 2,165 MB peak, 2,057 MB steady | 2.81 GB                 | **4 GB**                                      |
| API cold start to ready (this laptop) | 18.7 s median, 44 s worst      | —                       | Readiness must gate traffic; no scale-to-zero |
| Database                              | 190 MB, 3× transient           | 1 GB RAM is ample       | Smallest managed PostGIS plan                 |
| Web                                   | 86 MB resident                 | —                       | Smallest tier, or static hosting if exported  |

Rejected on these numbers, before price is considered:

- **Any API tier under 1.5 GB.** 1 GB ran with 6% headroom.
- **Two workers on anything under 4 GB.**
- **Scale-to-zero or sleeping API hosting** (Render Free, Fly's default
  auto-stop, Railway sleeping): every wake is a 19–44 s window in which the
  service is up and cannot route, and the graph cannot be kept warm across it.
- **Serverless functions for the API** (Vercel Functions, Cloudflare Workers,
  Netlify Functions): a 128 MB isolate cannot hold the graph, and a 2 GB
  function that rebuilds it per cold invocation turns a 120 ms route into a
  15 s one. The web tier can live there; the API cannot.
- **PostgreSQL without documented PostGIS support**, and **free database tiers
  that pause or expire** (Neon Free suspends after 5 min and cannot be
  disabled; Supabase Free pauses after a week and caps at 500 MB — the dataset
  is 190 MB today and 544 MB while loading; Render's free Postgres expires
  after 30 days).

## Options compared

All prices from the providers' own pages, accessed 2026-09-11. Bank of Canada
indicative rates that day: USD 1.3866, EUR 1.6086 CAD. Every figure is for an
always-on single-worker API; the two-worker variant is given where it changes
the total. Taxes are excluded everywhere.

### A. DigitalOcean App Platform + Managed PostgreSQL, Toronto — recommended

| Component   | Tier                                                        |                USD/mo | Source                                                                                       |
| ----------- | ----------------------------------------------------------- | --------------------: | -------------------------------------------------------------------------------------------- |
| API         | `apps-s-1vcpu-2gb` — 1 shared vCPU, 2 GiB, 200 GiB transfer |                 25.00 | [App Platform pricing](https://docs.digitalocean.com/products/app-platform/details/pricing/) |
| Web         | `apps-s-1vcpu-1gb` — 1 shared vCPU, 1 GiB                   |                 12.00 | same                                                                                         |
| Database    | Managed PostgreSQL 1 GiB / 1 vCPU / 10 GiB, single node     |                 15.15 | [Managed Databases pricing](https://www.digitalocean.com/pricing/managed-databases)          |
| **Total**   |                                                             | **52.15 ≈ CAD 72.31** |                                                                                              |
| Two workers | `apps-s-2vcpu-4gb` 50.00 instead of 25.00                   |    77.15 ≈ CAD 106.98 |                                                                                              |

- **Region.** Toronto (`tor`) is available for App Platform and Managed
  Databases ([availability](https://docs.digitalocean.com/platform/regional-availability/)).
- **PostGIS.** Listed as a supported extension for PostgreSQL 14–18
  ([supported extensions](https://docs.digitalocean.com/products/databases/postgresql/details/supported-extensions/));
  PostgreSQL 17 supported ([limits](https://docs.digitalocean.com/products/databases/postgresql/details/limits/)).
- **Backups.** Daily full backups with point-in-time restore over the previous
  seven days, restoring to a new node ([features](https://docs.digitalocean.com/products/databases/postgresql/details/features/)).
- **Health checks, rollback, secrets, logs, metrics.** HTTP health checks with
  configurable thresholds, and a failing liveness check restarts the container
  ([health checks](https://docs.digitalocean.com/products/app-platform/how-to/manage-health-checks/));
  rollback to any of the ten most recent successful deployments
  ([deployments](https://docs.digitalocean.com/products/app-platform/how-to/manage-deployments/));
  encrypted environment variables, decrypted only in the runtime
  ([variables](https://docs.digitalocean.com/products/app-platform/how-to/use-environment-variables/));
  CPU, memory, restarts, request rate and P95 latency with alerts
  ([insights](https://docs.digitalocean.com/products/app-platform/how-to/view-insights/)).
  **Runtime logs do not persist** without forwarding
  ([logs](https://docs.digitalocean.com/products/app-platform/how-to/view-logs/)) —
  a PA-RR-04 item.
- **Domain and TLS.** Custom domains with Let's Encrypt or Google Trust
  certificates ([domains](https://docs.digitalocean.com/products/app-platform/how-to/manage-domains/));
  a `*.ondigitalocean.app` hostname is provided, so a custom domain is
  optional.
- **Variable charges.** Outbound transfer beyond the included allowance at
  $0.02/GiB ([bandwidth](https://docs.digitalocean.com/products/billing/bandwidth/));
  database storage beyond 10 GiB at $0.215/GiB. The 158 KB cross-town response
  puts 200 GiB at roughly 1.3 million long routes a month.
- **Sleep / free tier.** Services do not sleep; the only free allowance is up
  to three static-only apps. Note the docs' database pricing page still says
  "$15.00" where the marketing page says $15.15 — verify in the control panel.
- **Why this one.** The only candidate with a Canadian region, documented
  PostGIS on PostgreSQL 17, seven-day point-in-time restore and application
  health checks that restart a failed container, at a price within a few
  dollars of the alternatives.

### B. Fly.io Machines + Managed Postgres, Toronto — fallback, with one precondition

| Component        | Tier                                                                 |                USD/mo | Source                                            |
| ---------------- | -------------------------------------------------------------------- | --------------------: | ------------------------------------------------- |
| API              | `shared-cpu-2x`, 2 GB, `auto_stop_machines = "off"`                  |                 11.83 | [Fly pricing](https://fly.io/docs/about/pricing/) |
| Web              | `shared-cpu-1x`, 1 GB                                                |                  5.92 | same                                              |
| Database         | Managed Postgres Basic — shared-2x, 1 GB, primary + replica, backups |                 38.00 | [MPG overview](https://fly.io/docs/mpg/overview/) |
| Database storage | 10 GB minimum at $0.28/GB                                            |                  2.80 | same                                              |
| **Total**        |                                                                      | **58.55 ≈ CAD 81.19** |                                                   |
| Two workers      | `shared-cpu-2x` 4 GB at 22.22 instead of 11.83                       |     68.94 ≈ CAD 95.59 |                                                   |

- **Region.** Toronto (`yyz`), including for Managed Postgres
  ([regions](https://fly.io/docs/reference/regions/)). The pricing page says
  prices vary by region and the Toronto markup, if any, was not verified.
- **PostGIS — the precondition.** Managed Postgres documents PostGIS on its
  default PostgreSQL 16 ([extensions](https://fly.io/docs/mpg/extensions/));
  PostgreSQL 17 clusters exist but are created through the dashboard only, and
  **no official page states that PostGIS is available on a PG17 cluster**
  ([staff post](https://community.fly.io/t/you-asked-and-we-shipped-postgres-17-on-mpg/26430)).
  Either confirm that with Fly before buying, or accept PostgreSQL 16 (nothing
  in the migrations needs 17; the Compose stack pins 17, which would then be a
  version skew to record). The legacy unmanaged Fly Postgres is
  [not a managed database](https://fly.io/docs/postgres/getting-started/what-you-should-know/)
  and needs a forked image for PostGIS; it is not considered.
- **Backups.** MPG keeps backups ten days and restores, including to a point in
  time, into a new cluster ([mpg](https://fly.io/mpg/), [flyctl mpg](https://fly.io/docs/flyctl/mpg/)).
- **Always-on.** `fly launch` defaults to stopping idle machines; keep the API
  up with `auto_stop_machines = "off"` or `min_machines_running = 1`
  ([autostop](https://fly.io/docs/launch/autostop-autostart/)).
- **Health checks, rollback, secrets, logs, metrics.** HTTP checks in
  `fly.toml` with rolling/canary/blue-green deploys ([deploy](https://fly.io/docs/apps/deploy/));
  rollback by redeploying a previous image ([rollback](https://fly.io/docs/blueprints/rollback-guide/));
  secrets in an encrypt-only vault ([secrets](https://fly.io/docs/apps/secrets/));
  logs searchable for 7 days, Prometheus metrics about 15 days
  ([logging](https://fly.io/docs/monitoring/logging-overview/), [metrics](https://fly.io/docs/monitoring/metrics/)).
- **Variable charges.** Egress $0.02/GB in North America with no included
  allowance; certificates free for the first ten hostnames
  ([custom domains](https://fly.io/docs/networking/custom-domain/)). No plan
  minimum on Pay As You Go; the free trial is 2 hours of runtime or 7 days
  ([trial](https://fly.io/docs/about/free-trial/)).
- **Why fallback.** Cheapest Canadian compute by far and the database is
  high-availability by default, but the database floor is $38 and the
  PostGIS-on-17 question is open.

### C. Render Web Service + Render Postgres, Ohio — viable if Canada is not required

| Component | Tier                                 |                                                                 USD/mo | Source                                                                                                                                                                 |
| --------- | ------------------------------------ | ---------------------------------------------------------------------: | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| API       | `1c-2g` (Standard) — 1 vCPU, 2 GB    |                                                                  25.00 | [Render on Render vs Railway](https://render.com/articles/render-vs-railway) (official article; the pricing page is client-rendered and could not be read)             |
| Web       | `0.5c-512mb` (Starter)               |                                                                   7.00 | same                                                                                                                                                                   |
| Database  | Postgres `0.5c-1g`, storage $0.30/GB | ~19–20 (**secondary source; not verified on an official page**) + 0.30 | [compute plans](https://render.com/docs/compute-plans), [storage price](https://render.com/articles/how-much-does-cloud-application-hosting-cost-for-small-businesses) |
| **Total** |                                      |                    **≈ 51–52 ≈ CAD 71–72**, database figure unverified |                                                                                                                                                                        |

- No Canadian region: Oregon, Ohio, Virginia, Frankfurt, Singapore
  ([regions](https://render.com/docs/regions)). PostGIS documented for
  PostgreSQL 13–18 ([extensions](https://render.com/docs/postgresql-extensions)).
  Paid Postgres has continuous point-in-time recovery, 3 days on the free
  Hobby workspace and 7 on Pro ([backups](https://render.com/docs/postgresql-backups)).
  Health checks stop traffic after 15 s of failure and restart after 60 s
  ([health checks](https://render.com/docs/health-checks)). Free web services
  sleep after 15 minutes idle and free databases expire after 30 days
  ([free](https://render.com/docs/free)) — neither is usable here.
- **Variable charges.** Only 5 GB of outbound bandwidth is included on the
  Hobby workspace, then $0.15/GB ([bandwidth](https://render.com/docs/outbound-bandwidth));
  the Pro workspace ($25/mo) raises that to 25 GB. At 158 KB per long route,
  5 GB is about 33,000 routes — enough for a demo, not for a public pilot.

### D. Hetzner Cloud CX23, Nuremberg or Helsinki, self-managed — the budget shape, not recommended yet

| Component                             | Tier                                           |                                                                                   EUR/mo | Source                                                                                                            |
| ------------------------------------- | ---------------------------------------------- | ---------------------------------------------------------------------------------------: | ----------------------------------------------------------------------------------------------------------------- |
| One server for API + web + PostgreSQL | CX23 — 2 vCPU, 4 GB, 40 GB NVMe, 20 TB traffic |                                                                                     5.49 | [price adjustment 2026-06-15](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/) |
| IPv4 address                          |                                                |                                                                                     0.50 | [IPv4 pricing](https://docs.hetzner.com/general/others/ipv4-pricing/)                                             |
| **Total**                             |                                                | **5.99 ≈ CAD 9.64** (plus ~20% for server backups, figure seen only in a search snippet) |                                                                                                                   |

- No Canadian or US location for the CX line (US locations sell the CPX line,
  where 4 GB is €31.99) ([locations](https://docs.hetzner.com/cloud/general/locations/)).
  No managed PostgreSQL on Hetzner Cloud
  ([managed databases are a separate product](https://docs.hetzner.com/managed/databases/postgresql/)).
- This repository's own Compose file plus a reverse proxy would run on it, and
  4 GB holds one API worker, PostgreSQL and the web server. What it does not
  give is anything Gate D requires: backups, restore, rollback and metrics
  would all be ours to build and to prove. Until PA-RR-04 has exercised a
  backup and restore on a schedule, recommending this shape would be
  recommending a database with no safety net for the sake of $60 a month.

### E. Railway — rejected

No Canadian region ([regions](https://docs.railway.com/reference/regions)),
PostGIS only via a community template rather than the official one
([PostgreSQL guide](https://docs.railway.com/guides/postgresql)), and health
checks are evaluated only during a deployment, not while the service runs
([health checks](https://docs.railway.com/reference/healthchecks)). At $10/GB
of RAM and $20/vCPU a month ([pricing](https://docs.railway.com/reference/pricing/plans)),
the shape would cost about as much as A with fewer of the guarantees.

### Frontend alternatives, any option

The web tier is a 86 MB Node process today. If the app is exported statically
it could be served free on DigitalOcean static sites, Cloudflare (static
assets are free and unlimited, [billing](https://developers.cloudflare.com/workers/static-assets/billing-and-limitations/))
or Netlify's free credits; Vercel's Hobby plan is restricted to
"non-commercial personal use" ([fair use](https://vercel.com/docs/limits/fair-use-guidelines))
and is not relied on. Whether the app can be exported statically was not
tested and is not assumed: the totals above pay for a container.

## Decision (proposed)

**Primary: Option A**, DigitalOcean App Platform in Toronto —
`apps-s-1vcpu-2gb` for the API with `GRAPH_PRELOAD_REGIONS=waterloo`, a 1 GiB
web service, and a 1 GiB single-node Managed PostgreSQL with PostGIS —
**about USD 52 / CAD 72 a month** before tax and usage, with outbound transfer
and database storage as the only variable charges.

**Fallback: Option B**, Fly.io in Toronto at about USD 59 / CAD 81, on the
explicit condition that PostGIS on a PostgreSQL 17 Managed Postgres cluster is
confirmed with Fly first, or PostgreSQL 16 is accepted and recorded.

**One worker.** The memory measurements say two workers need 4 GB, and the
probe says one worker serves people one at a time with visible queueing beyond
two or three concurrent long routes. For a pilot shown to individual people,
one worker on 2 GB is the right trade; the day queueing is observed in real
traffic, the answer is the 4 GB tier of the same provider, not a smaller
graph.

**Headroom.** 2 GB against a measured 1,083 MB peak is 1.85×, comfortably
above the 30% this decision was required to keep, and it is the smallest tier
either recommended provider sells above 1.41 GB.

## What the founder decides

1. Provider and tier: A as proposed, B, or something else.
2. Whether a Canadian region is a requirement or a preference. If it is not,
   C becomes comparable.
3. Payment method and account creation — nothing here has been signed up for.
4. Custom domain: optional with either recommendation; both provide a
   hostname and a certificate. A registrar fee was not researched.
5. Whether one worker is acceptable for the pilot, given the probe.

## Consequences

- The API image gains a startup preload and a third readiness check; the
  development default is unchanged and lazy.
- `docs/evidence/production-envelope.json` and the procedure behind it become
  the baseline every later hosting change is measured against.
- KI-6 is restated in container terms: ~1 GB resident per worker, ~19 s to
  ready on this laptop, graph duplicated per worker.
- PA-RR-04 (observability) has two concrete jobs whichever option is chosen:
  log forwarding, because neither recommended provider retains runtime logs
  for long by default, and a scheduled, exercised backup-and-restore.
- Nothing about routing, the graph representation or the data changed.
