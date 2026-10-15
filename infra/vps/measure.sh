#!/bin/sh
# Measure the running pilot on this host: API cold starts and memory.
#
#   measure.sh [runs]        default 3
#
# Each run force-recreates the API container alone (the database, web server
# and Caddy keep running) and records, on this host's clock, the seconds from
# `compose up` to /health/live and to /health/ready, plus the graph load time
# the readiness body reports. It then waits for the process to settle and reads
# the container's cgroup memory: memory.current, and memory.peak — the cgroup's
# own high-water mark since the container started, which no sampling can miss
# and which is what the 1536m limit is enforced against.
#
# Finally, every container's memory and the host's, once. Output is one JSON
# object per line, for docs/evidence/vps-deployment.json.
#
# This restarts the API: expect ~30-45 s in which routes return 502.

set -eu

ROOT="${PATHABLE_ROOT:-/srv/pathable}"
STACK="$ROOT/stack"
RUNS="${1:-3}"
SETTLE_SECONDS="${SETTLE_SECONDS:-30}"

compose() {
    docker compose --project-directory "$STACK" -f "$STACK/compose.yaml" \
        --env-file "$ROOT/secrets/pathable.env" --env-file "$ROOT/site.env" \
        --env-file "$ROOT/release.env" "$@"
}
now() { date +%s.%N; }
elapsed() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.2f", b - a }'; }
mib() { awk -v b="$1" 'BEGIN { printf "%.1f", b / 1048576 }'; }

cgroup_file() {
    id="$(docker inspect --format '{{.Id}}' "$1")"
    cat "/sys/fs/cgroup/system.slice/docker-$id.scope/$2"
}

probe() {
    docker exec pathable-api-1 python -c "
import sys, urllib.request
try:
    r = urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/$1', timeout=3)
    print(r.read().decode()); sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null
}

run=1
while [ "$run" -le "$RUNS" ]; do
    started="$(now)"
    compose up -d --no-deps --force-recreate api >/dev/null 2>&1
    live=""
    until body="$(probe ready)"; do
        if [ -z "$live" ] && probe live >/dev/null; then live="$(elapsed "$started" "$(now)")"; fi
        sleep 0.25
    done
    ready="$(elapsed "$started" "$(now)")"
    [ -n "$live" ] || live="$ready"
    graph="$(printf '%s' "$body" | sed -n 's/.*loaded in \([0-9.]*\) s.*/\1/p')"
    sleep "$SETTLE_SECONDS"
    printf '{"measure":"api_cold_start","run":%s,"live_s":%s,"ready_s":%s,"graph_load_s":%s,"memory_current_mib":%s,"memory_peak_mib":%s,"settle_s":%s}\n' \
        "$run" "$live" "$ready" "${graph:-null}" \
        "$(mib "$(cgroup_file pathable-api-1 memory.current)")" \
        "$(mib "$(cgroup_file pathable-api-1 memory.peak)")" "$SETTLE_SECONDS"
    run=$((run + 1))
done

for name in pathable-db-1 pathable-api-1 pathable-web-1 pathable-caddy-1; do
    printf '{"measure":"container_memory","container":"%s","memory_current_mib":%s,"memory_peak_mib":%s,"memory_max_mib":%s,"started_at":"%s"}\n' \
        "$name" \
        "$(mib "$(cgroup_file "$name" memory.current)")" \
        "$(mib "$(cgroup_file "$name" memory.peak)")" \
        "$(mib "$(cgroup_file "$name" memory.max)")" \
        "$(docker inspect --format '{{.State.StartedAt}}' "$name")"
done
free -m | awk '/^Mem:/ {m=$2; u=$3; a=$7} /^Swap:/ {st=$2; su=$3}
    END {printf "{\"measure\":\"host_memory\",\"total_mib\":%s,\"used_mib\":%s,\"available_mib\":%s,\"swap_total_mib\":%s,\"swap_used_mib\":%s}\n", m, u, a, st, su}'
