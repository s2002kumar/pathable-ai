# The public pilot on one VPS

PathAble's Waterloo pilot is served at **<https://51.222.36.79>** from one
OVH VPS. This is the runbook: what runs there, how it was built from nothing,
and how to deploy, roll back, back up, restore and read the logs. The decision
is recorded in [ADR 0009](../adr/0009-deployment-architecture.md); the
measurements are in
[`docs/evidence/vps-deployment.json`](../evidence/vps-deployment.json).

It is a pilot on a single host. Nothing here is highly available, and the
limits are in [KI-12 and KI-13](../development/KNOWN_ISSUES.md).

## What runs

| Host            | OVH VPS, Ubuntu 26.04 LTS, 2 vCPU, 3.7 GiB RAM, 38 GB disk, 2 GiB swap    |
| --------------- | ------------------------------------------------------------------------- |
| Public          | TCP 80 and 443, UDP 443 (Caddy); TCP 22 (SSH, keys only)                  |
| Not public      | PostgreSQL, the API and the web server have no host port at all           |
| Compose project | `pathable`, from [`infra/vps/compose.yaml`](../../infra/vps/compose.yaml) |

```
internet ─▶ caddy :80/:443 ──┬─ /api/v1/* ─▶ api :8000 (one worker, Waterloo graph in memory)
            Let's Encrypt    └─ everything else ─▶ web :3000 (Next.js standalone)
                                          api ─▶ db :5432 (PostGIS, network with no route out)
```

| Service | Image                     | Memory limit | Notes                                                               |
| ------- | ------------------------- | -----------: | ------------------------------------------------------------------- |
| `db`    | `postgis/postgis:17-3.5`  |        1 GiB | Network `data` only, which is `internal`                            |
| `api`   | `pathable-api:<full SHA>` |      1.5 GiB | Connects as `pathable_app`: not a superuser, owns only its database |
| `web`   | `pathable-web:<full SHA>` |      512 MiB | Built with `NEXT_PUBLIC_API_BASE_URL` = the public origin           |
| `caddy` | `caddy:2.11.7-alpine`     |      256 MiB | The only container with published ports                             |

API, web and Caddy run with `no-new-privileges` and drop every capability
(Caddy keeps `NET_BIND_SERVICE`). The API and web processes run as uid 10001.

**Which revision is live.** `curl https://51.222.36.79/api/v1/health/live`
returns `"version": "0.1.0+<first 12 of the SHA>"`. On the host,
`deploy.sh status` prints the full SHA, the previous one and the database
revision; the images are tagged with the full SHA and carry it in their
`org.opencontainers.image.revision` label.

## Layout on the host

```
/srv/pathable/repo                  clone of the public repository; tooling runs from here
/srv/pathable/stack                 compose.yaml, Caddyfile, db-init/ in use (copied by deploy.sh)
/srv/pathable/secrets/pathable.env  0600: POSTGRES_SUPERUSER_PASSWORD, PATHABLE_DB_PASSWORD
/srv/pathable/site.env              PATHABLE_HOST, PATHABLE_TLS_PROFILE (not secret)
/srv/pathable/release.env           the revision being served; release.env.previous before it
/srv/pathable/deployments.log       one line per switch, with its live and ready times
/var/backups/pathable/              pg_dump archives and their .sha256 files
```

**Secrets.** The two database passwords were generated on the host with
`openssl rand -hex 32`, live only in `secrets/pathable.env` (mode 0600, owner
`ubuntu`), and have never been printed, committed or copied off the host. No
image contains a credential. The superuser is used only over the container's
local socket, by `backup.sh` and `restore.sh`; nothing logs in as it over the
network.

## From nothing to serving

This is the sequence that built the pilot on 2026-10-14/15.

1. **Host.** `sudo sh infra/vps/provision-host.sh` — Ubuntu's own Docker,
   Compose and buildx packages, 2 GiB swap at `vm.swappiness=10`, key-only SSH
   for `ubuntu` with no root login, ufw allowing 22, 80, 443 (TCP) and 443
   (UDP), fail2ban on SSH, rotated Docker logs (`10m` × 5 per container),
   `live-restore`, and unattended security upgrades with a reboot at 08:30 UTC
   when one is required. Idempotent. Reboot after the first run.
2. **Repository and configuration.**

   ```bash
   git clone https://github.com/s2002kumar/pathable-ai.git /srv/pathable/repo
   umask 077
   printf 'POSTGRES_SUPERUSER_PASSWORD=%s\nPATHABLE_DB_PASSWORD=%s\n' \
     "$(openssl rand -hex 32)" "$(openssl rand -hex 32)" > /srv/pathable/secrets/pathable.env
   printf 'PATHABLE_HOST=51.222.36.79\nPATHABLE_TLS_PROFILE=shortlived\n' > /srv/pathable/site.env
   ```

3. **Database.** `infra/vps/deploy.sh init origin/main` builds both images,
   starts PostGIS — whose first start runs
   [`db-init/20-pathable.sh`](../../infra/vps/db-init/20-pathable.sh) to create
   the role, the database and the two extensions — and migrates it to head as
   the application role. It serves nothing.
4. **Dataset.** A data-only archive of the five map tables and the two
   place-index tables, exported from a database holding the verified dataset,
   copied to the host and restored as the application role:

   ```bash
   sh infra/production-smoke/restore-dataset.sh --dump waterloo-main-data.dump \
     --container pathable-db-1 --user pathable_app --db pathable
   ```

   Then the content checksum is **recomputed from the restored rows** and
   compared with the one in
   [`waterloo-dataset-lifecycle.json`](../evidence/waterloo-dataset-lifecycle.json)
   before it is recorded — never recorded first:

   ```bash
   pathable datasets checksum 51585450            # must print 4a179dc0…bc5238f00
   pathable datasets checksum --record 51585450
   ```

   The place index is restored rather than rebuilt: its rows carry the SHA-256
   and data date of the extract they were read from, the same extract as the
   network. Rebuilding it needs the 970 MB extract on the host.

5. **Serve.** `infra/vps/deploy.sh up origin/main`.
6. **Backups.** Copy the two units from `infra/vps/systemd/` to
   `/etc/systemd/system/` and `systemctl enable --now pathable-backup.timer`.

## Deploying

```bash
/srv/pathable/repo/infra/vps/deploy.sh up origin/main      # or a tag, or a SHA on main
```

What it does, in order: refuses a commit that is not on `origin/main` (unless
`ALLOW_UNMERGED=1`); builds `pathable-api:<sha>` and `pathable-web:<sha>` from
`git archive <sha>` — never from a working tree — unless they exist; takes a
`pre-deploy` backup, and refuses to continue if the database is running but
cannot be read; restarts the API alone and waits for `/health/ready`; then
brings up web and Caddy; and appends to `deployments.log`.

The tooling (this directory) runs from whatever `/srv/pathable/repo` has
checked out; the application comes from the SHA you name. Pull the repository
first when the tooling itself changed.

**Expect about a minute without routing.** The API is a single process holding
the graph: the old one takes ~9 s to exit, the new one ~42 s to load the graph
and become ready. Measured from outside, routing was unavailable for about
55 s per switch, and the landing page for a few seconds (two consecutive
2-second samples) when its container was recreated. Otherwise the page stays
up and says the service is unavailable.

To change the public host (for example, when a domain exists): point its DNS
`A` record at `51.222.36.79`, set `PATHABLE_HOST=<domain>` and
`PATHABLE_TLS_PROFILE=classic` in `site.env`, and run `deploy.sh up` — the web
image is rebuilt because the origin is compiled into its bundle.

## Rolling back

```bash
/srv/pathable/repo/infra/vps/deploy.sh rollback
```

Switches to `release.env.previous`, using its images, which stay on the host.
Running it twice toggles between the two releases.

It **refuses** when the database's Alembic revision is not the previous
release's head: an older API cannot start on a schema a newer release
migrated, and would restart forever. In that case restore the `pre-deploy`
backup the forward deploy took, then roll back:

```bash
/srv/pathable/repo/infra/vps/restore.sh --into production --yes \
  --dump /var/backups/pathable/pathable-<time>-pre-deploy-<sha>.dump
/srv/pathable/repo/infra/vps/deploy.sh rollback
```

Exercised on 2026-10-15: `up 465bab7` (the previous merge on `main`) ready in
53.1 s, then `rollback` back to `a3f6448` in 51.6 s; the public version
followed each switch. The refusal path has not been exercised, because no
release since 0007 has changed the schema.

## Backups and restore

`backup.sh` writes a full custom-format `pg_dump` of the `pathable` database
(32 MB, about 6 s) with a `.sha256` beside it: daily at 07:15 UTC from the
systemd timer, before every deploy, and before every production restore.
Files older than 14 days are deleted, never below the newest three.

**They are on the same disk as the database.** They cover a bad deploy, a bad
migration and operator error, not losing the host. Until off-host storage
exists, copy one off by hand:

```bash
scp ubuntu@51.222.36.79:/var/backups/pathable/pathable-<time>-scheduled-<sha>.dump{,.sha256} .
```

**Proving a backup restores** — non-destructive, any time:

```bash
/srv/pathable/repo/infra/vps/restore.sh --into scratch          # newest backup
```

Restores into a throwaway PostGIS container on its own internal network,
checks the revision, node, segment and place-index counts, the sealed-dataset
triggers and the role, then recomputes the dataset's content checksum with
the release's own image, and removes the container.

**Disaster recovery** — replaces the live database:

```bash
/srv/pathable/repo/infra/vps/restore.sh --into production --yes [--dump FILE]
```

Takes a `pre-restore` safety backup, stops the API, drops and recreates the
database from the dump, runs the same verification, and starts the API only if
it passed. Exercised on 2026-10-15: 6.5 s of `pg_restore`, checksum matched,
94.9 s from stopping the API to ready again (30 s of that is the checksum).

Images built from `a3f6448` cannot start the `pathable` CLI (pyosmium needs
`libexpat1`, which the base image stopped carrying; fixed in
`services/api/Dockerfile`). For those, `restore.sh` takes
`PATHABLE_CLI_IMAGE=pathable-api-cli:<sha>`, built on the host as the release
image plus that one library:

```bash
printf 'FROM pathable-api:%s\nUSER root\nRUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*\nUSER pathable\n' "$SHA" \
  | docker build -t "pathable-api-cli:$SHA" -
```

## Logs

All four containers log to stdout as JSON where the process supports it, kept
by Docker as `json-file`, rotated at 10 MB with five files per container.

```bash
cd /srv/pathable/stack
docker compose --env-file ../secrets/pathable.env --env-file ../site.env --env-file ../release.env logs -f api
docker logs --since 1h pathable-caddy-1          # access log
journalctl -u pathable-backup.service           # backups
```

- **API**: structured JSON, each line tagged with the service, environment and
  version. A route's or search's content is never logged — "Requests are not
  persisted", and the search query is deliberately absent from its log line.
- **Caddy**: one JSON line per request. Client addresses are truncated before
  they are written (IPv4 to /24, IPv6 to /48), and request bodies, where a
  route's origin and destination are, are never logged.
- **PostgreSQL**: statements slower than one second.

There is no metrics collection and no alerting. Nobody is told when the site
is down ([KI-12](../development/KNOWN_ISSUES.md)).

## Rate limits

Each client may make **30 route comparisons and 60 searches a minute** (each
figure is both the burst and the refill a minute). Past that the API answers
HTTP 429 with `Retry-After` and code `rate_limited`, and the planner shows that
message. Health, readiness and the profile list are never limited. The limiter
lives in the API process
([`core/rate_limit.py`](../../services/api/src/pathable_api/core/rate_limit.py),
[KI-13](../development/KNOWN_ISSUES.md)), so there is nothing to run beside it.

The client is the `X-Forwarded-For` entry Caddy writes (`TRUSTED_PROXY_HOPS=1`
in [`compose.yaml`](../../infra/vps/compose.yaml)); Caddy discards any a client
sends. That is only safe because the API has no host port — **never publish
port 8000 while `TRUSTED_PROXY_HOPS` is set**, or anyone could choose their own
client address. To change a limit, set `RATE_LIMIT_ROUTES_PER_MINUTE` or
`RATE_LIMIT_SEARCHES_PER_MINUTE` in the API's environment and redeploy; a
refusal appears in the API log as a `Request completed` line with status 429.

## Smoke test and measurements

From any machine with Python 3.11+:

```bash
python infra/vps/smoke.py --url https://51.222.36.79 --expect-revision a3f6448aab55 \
  --runs 10 --concurrency 4 --json smoke.json
```

Sixteen checks: the certificate, the HTTP redirect, that 5432, 8000 and 3000
do not answer, both pages and their security headers, the reported revision,
readiness, the profiles, search for both ends of the journey recorded in
[`waterloo-place-search.json`](../evidence/waterloo-place-search.json), and
that journey's recorded answer — 406.4 m with 4 stairways, against 490.2 m
with none for a wheelchair, from dataset `51585450`, with no model
predictions. Then sequential and parallel route latency, and last, that the
rate limit refuses this client with a standard 429. It exits non-zero if
anything failed.

The script is one client, so it lives within one client's 30 routes a minute:
the defaults spend 21 before the rate-limit check, and a second run from the
same address within about a minute is refused — wait for the `Retry-After` it
reports. `--skip-rate-limit-check` leaves the budget unspent.

The real browser, against the public site:

```bash
FULLSTACK_TARGET=compose FULLSTACK_WEB_URL=https://51.222.36.79 \
FULLSTACK_API_URL=https://51.222.36.79 \
  pnpm --filter @pathable/web exec playwright test --config=playwright.fullstack.config.ts
```

On the host, `infra/vps/measure.sh 3` force-recreates the API three times and
records start to live and to ready, the graph load, and each container's
cgroup `memory.current` and `memory.peak`. It causes three outages of about a
minute.

## Certificates

Caddy obtains and renews certificates itself. An IP address can only have a
6-day Let's Encrypt certificate (the `shortlived` profile); Caddy renews it
well before expiry. Clients send no SNI to an IP address, so the Caddyfile
sets `default_sni` — without it every verifying client got a TLS
internal-error alert, because inside Docker the connection's local address is
the container's, not the public one.
