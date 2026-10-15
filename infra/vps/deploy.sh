#!/bin/sh
# Build and serve one Git revision of PathAble on this host.
#
#   deploy.sh build <ref>    build the two images for <ref>, serve nothing
#   deploy.sh init <ref>     first deployment only: build, start the database and
#                            migrate it to <ref>'s head, serve nothing. Restore
#                            the dataset next, then `up`.
#   deploy.sh up <ref>       build if needed, back up the database, switch, wait
#                            until the API is ready, record the release
#   deploy.sh rollback       switch back to the previous release's images
#   deploy.sh status         what is running, and from which revision
#
# RECREATE=1 with `up` restarts the API even if the revision is unchanged, which
# is how a cold start is measured.
#
# <ref> is anything `git rev-parse` resolves (origin/main, a tag, a SHA). It must
# be reachable from origin/main — the public pilot serves merged code only —
# unless ALLOW_UNMERGED=1.
#
# Images are built from `git archive <sha>`, not from a working tree, so nothing
# uncommitted can reach them, and are tagged with the full SHA. The revision is
# then visible in three places: the image tag and its OCI revision label,
# /srv/pathable/release.env, and the `version` field of /api/v1/health/live.
#
# Layout (see docs/deployment/VPS.md):
#   /srv/pathable/repo                  clone of the public repository
#   /srv/pathable/stack                 compose.yaml, Caddyfile, db-init/ in use
#   /srv/pathable/secrets/pathable.env  database passwords (0600)
#   /srv/pathable/site.env              PATHABLE_HOST, PATHABLE_TLS_PROFILE
#   /srv/pathable/release.env           current release; .previous is the one before
#   /srv/pathable/deployments.log       one line per switch

set -eu

ROOT="${PATHABLE_ROOT:-/srv/pathable}"
REPO="$ROOT/repo"
STACK="$ROOT/stack"
SECRETS="$ROOT/secrets/pathable.env"
SITE="$ROOT/site.env"
RELEASE="$ROOT/release.env"
HISTORY="$ROOT/deployments.log"
READY_TIMEOUT="${READY_TIMEOUT:-300}"
HERE="$(cd "$(dirname "$0")" && pwd)"

log() { printf '%s deploy: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"; }
die() { log "$1"; exit 1; }
now() { date +%s.%N; }
elapsed() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.1f", b - a }'; }

[ -f "$SECRETS" ] || die "missing $SECRETS (see docs/deployment/VPS.md, first deployment)"
[ -f "$SITE" ] || die "missing $SITE"
# shellcheck disable=SC1090
. "$SITE"
[ -n "${PATHABLE_HOST:-}" ] || die "PATHABLE_HOST is not set in $SITE"
case "$PATHABLE_HOST" in
    *[!A-Za-z0-9.:-]*) die "PATHABLE_HOST must be a bare host name or IP address" ;;
esac
# The one origin the site is served from, the web bundle calls and CORS allows.
PATHABLE_PUBLIC_URL="https://$PATHABLE_HOST"

compose() {
    docker compose --project-directory "$STACK" -f "$STACK/compose.yaml" \
        --env-file "$SECRETS" --env-file "$SITE" --env-file "$RELEASE" "$@"
}

release_value() { sed -n "s/^$2=//p" "$1" 2>/dev/null | head -n 1; }

resolve() {
    git -C "$REPO" fetch --quiet --tags origin
    sha="$(git -C "$REPO" rev-parse --verify --quiet "$1^{commit}")" || die "cannot resolve $1"
    if [ "${ALLOW_UNMERGED:-0}" != "1" ] && ! git -C "$REPO" merge-base --is-ancestor "$sha" origin/main; then
        die "refusing: $sha is not on origin/main (ALLOW_UNMERGED=1 overrides)"
    fi
    printf '%s\n' "$sha"
}

image_label() {
    docker image inspect --format "{{ index .Config.Labels \"$2\" }}" "$1" 2>/dev/null || true
}

build() {
    sha="$1"
    api_ok=0; web_ok=0
    docker image inspect "pathable-api:$sha" >/dev/null 2>&1 && api_ok=1
    # The web image has the public origin compiled into its bundle, so an image
    # built for another origin is not this release's image.
    [ "$(image_label "pathable-web:$sha" org.pathable.public-url)" = "$PATHABLE_PUBLIC_URL" ] && web_ok=1
    if [ "$api_ok" = "1" ] && [ "$web_ok" = "1" ]; then
        log "images for $sha already built"
        return 0
    fi

    src="$ROOT/build/$sha"
    rm -rf "$src"
    mkdir -p "$src"
    git -C "$REPO" archive "$sha" | tar -x -C "$src"
    created="$(git -C "$REPO" show -s --format=%cI "$sha")"
    labels="--label org.opencontainers.image.revision=$sha
            --label org.opencontainers.image.source=https://github.com/s2002kumar/pathable-ai
            --label org.opencontainers.image.created=$created"

    if [ "$api_ok" = "0" ]; then
        log "building pathable-api:$sha"
        started="$(now)"
        # shellcheck disable=SC2086
        docker build --quiet -f "$src/services/api/Dockerfile" --target runtime \
            -t "pathable-api:$sha" $labels "$src" >/dev/null
        log "  built in $(elapsed "$started" "$(now)")s"
    fi
    if [ "$web_ok" = "0" ]; then
        log "building pathable-web:$sha for $PATHABLE_PUBLIC_URL"
        started="$(now)"
        # shellcheck disable=SC2086
        docker build --quiet -f "$src/apps/web/Dockerfile" --target runtime \
            --build-arg "NEXT_PUBLIC_API_BASE_URL=$PATHABLE_PUBLIC_URL" \
            --label "org.pathable.public-url=$PATHABLE_PUBLIC_URL" \
            -t "pathable-web:$sha" $labels "$src" >/dev/null
        log "  built in $(elapsed "$started" "$(now)")s"
    fi
    rm -rf "$src"
}

db_revision() {
    compose exec -T db psql -U postgres -d pathable -At \
        -c "select version_num from alembic_version" 2>/dev/null || true
}

image_head() {
    docker run --rm --entrypoint alembic "pathable-api:$1" heads 2>/dev/null | awk '{print $1}'
}

api_ready_body() {
    compose exec -T api python -c '
import sys, urllib.request, urllib.error
try:
    r = urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health/ready", timeout=5)
    print(r.read().decode()); sys.exit(0)
except urllib.error.HTTPError as e:
    print(e.read().decode()); sys.exit(1)
except Exception as e:
    print(e); sys.exit(2)
' 2>/dev/null
}

api_live() {
    compose exec -T api python -c '
import sys, urllib.request
sys.exit(0 if urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health/live", timeout=3).status == 200 else 1)
' >/dev/null 2>&1
}

write_release() {
    sha="$1"
    version="$(git -C "$REPO" show "$sha:services/api/pyproject.toml" \
        | sed -n 's/^version = "\(.*\)"/\1/p' | head -n 1)"
    short="$(printf '%s' "$sha" | cut -c1-12)"

    previous="$(release_value "$RELEASE" PATHABLE_REVISION)"
    if [ -n "$previous" ] && [ "$previous" != "$sha" ]; then
        cp "$RELEASE" "$RELEASE.previous"
    fi

    # The stack files in use are the ones from this checkout; copied rather than
    # bind-mounted from the repository so a `git pull` never changes a running
    # container's Caddyfile underneath it.
    mkdir -p "$STACK/db-init"
    cp "$HERE/compose.yaml" "$HERE/Caddyfile" "$STACK/"
    cp "$HERE/db-init/20-pathable.sh" "$STACK/db-init/"

    tmp="$RELEASE.tmp"
    {
        echo "PATHABLE_REVISION=$sha"
        echo "PATHABLE_APP_VERSION=${version}+${short}"
        echo "PATHABLE_DEPLOYED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } > "$tmp"
    mv "$tmp" "$RELEASE"
}

switch_to() {
    sha="$1"
    previous="$(release_value "$RELEASE" PATHABLE_REVISION)"
    write_release "$sha"
    log "switching to $sha ($(release_value "$RELEASE" PATHABLE_APP_VERSION))"
    compose up -d db
    # The API on its own first, so live and ready are timed from its own start
    # rather than from whenever Compose finished waiting on health checks.
    started="$(now)"
    # RECREATE=1 restarts the API even when nothing changed: a cold start, measured.
    if [ "${RECREATE:-0}" = "1" ]; then
        compose up -d --no-deps --force-recreate api
    else
        compose up -d --no-deps api
    fi

    live_at=""
    deadline=$(( $(date +%s) + READY_TIMEOUT ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if [ -z "$live_at" ] && api_live; then
            live_at="$(elapsed "$started" "$(now)")"
            log "  live after ${live_at}s"
        fi
        if body="$(api_ready_body)"; then
            ready_at="$(elapsed "$started" "$(now)")"
            log "  ready after ${ready_at}s"
            log "  $body"
            # Web and Caddy follow only once the API can route.
            compose up -d --remove-orphans
            printf '%s %s previous=%s live_s=%s ready_s=%s by=%s\n' \
                "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$sha" "${previous:-none}" \
                "$live_at" "$ready_at" "$(id -un)" >> "$HISTORY"
            return 0
        fi
        sleep 1
    done
    log "the API did not become ready within ${READY_TIMEOUT}s; last readiness body:"
    log "  ${body:-none}"
    compose logs --tail 40 api >&2 || true
    die "deploy of $sha FAILED. To go back: $0 rollback"
}

case "${1:-}" in
    build)
        [ -n "${2:-}" ] || die "usage: $0 build <ref>"
        build "$(resolve "$2")"
        ;;
    init)
        [ -n "${2:-}" ] || die "usage: $0 init <ref>"
        [ ! -f "$RELEASE" ] || die "refusing: $RELEASE exists, so this host is already initialised"
        sha="$(resolve "$2")"
        build "$sha"
        write_release "$sha"
        compose up -d db
        until [ "$(docker inspect --format '{{.State.Health.Status}}' pathable-db-1)" = "healthy" ]; do
            sleep 2
        done
        # The entrypoint migrates to head before it runs the command it is given.
        compose run --rm --no-deps api alembic current
        log "database migrated. Restore the dataset (docs/deployment/VPS.md), then: $0 up $2"
        ;;
    up)
        [ -n "${2:-}" ] || die "usage: $0 up <ref>"
        sha="$(resolve "$2")"
        build "$sha"
        if [ -n "$(db_revision)" ]; then
            "$HERE/backup.sh" "pre-deploy"
        fi
        switch_to "$sha"
        ;;
    rollback)
        [ -f "$RELEASE.previous" ] || die "no previous release recorded"
        target="$(release_value "$RELEASE.previous" PATHABLE_REVISION)"
        docker image inspect "pathable-api:$target" >/dev/null 2>&1 \
            || die "pathable-api:$target is no longer on this host; rebuild it with: $0 build $target"
        # An older API cannot start on a database a newer release migrated past
        # its head: Alembic would refuse, and the container would restart forever.
        current_db="$(db_revision)"
        target_head="$(image_head "$target")"
        if [ -n "$current_db" ] && [ "$current_db" != "$target_head" ]; then
            log "refusing: the database is at $current_db but $target expects $target_head."
            log "Restore the pre-deploy backup first (restore.sh --into production), then roll back."
            exit 1
        fi
        build "$target"
        switch_to "$target"
        ;;
    status)
        log "release: $(release_value "$RELEASE" PATHABLE_REVISION) ($(release_value "$RELEASE" PATHABLE_APP_VERSION)), deployed $(release_value "$RELEASE" PATHABLE_DEPLOYED_AT)"
        log "previous: $(release_value "$RELEASE.previous" PATHABLE_REVISION)"
        log "database: $(db_revision)"
        compose ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}'
        ;;
    *)
        sed -n '2,12p' "$0"
        exit 2
        ;;
esac
