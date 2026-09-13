# syntax=docker/dockerfile:1.7
#
# PathAble web image. Build context is the repository root:
#   docker build -f apps/web/Dockerfile .

FROM node:26-bookworm-slim AS base
ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    CI=true
RUN corepack enable

# -----------------------------------------------------------------------------
# Dependencies — cached until a manifest or the lockfile changes
# -----------------------------------------------------------------------------
FROM base AS deps
WORKDIR /repo

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY apps/web/package.json apps/web/
COPY packages/contracts/package.json packages/contracts/

RUN --mount=type=cache,target=/pnpm/store \
    pnpm install --frozen-lockfile

# -----------------------------------------------------------------------------
# Builder
# -----------------------------------------------------------------------------
FROM base AS builder
WORKDIR /repo

COPY --from=deps /repo/node_modules ./node_modules
COPY --from=deps /repo/apps/web/node_modules ./apps/web/node_modules
COPY --from=deps /repo/packages/contracts/node_modules ./packages/contracts/node_modules

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY packages/contracts ./packages/contracts
COPY apps/web ./apps/web

# The web package's `prebuild` runs scripts/sync-maplibre-worker.mjs, which
# copies MapLibre's tile worker into public/. Without it the build fails, and
# without the worker the map silently renders nothing at all (see KI-1).
COPY scripts ./scripts

# NEXT_PUBLIC_* values are substituted into the client bundle at build time, so
# they must be present now rather than at run time. None of them may be a secret:
# everything below ships to every visitor's browser in plain text.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ARG NEXT_PUBLIC_MAP_STYLE_URL=https://tiles.openfreemap.org/styles/liberty
ARG NEXT_PUBLIC_PILOT_CENTER_LAT=43.4668
ARG NEXT_PUBLIC_PILOT_CENTER_LON=-80.5164
ARG NEXT_PUBLIC_PILOT_ZOOM=14
ARG NEXT_PUBLIC_PILOT_REGION_NAME="Waterloo, Ontario"

ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_MAP_STYLE_URL=$NEXT_PUBLIC_MAP_STYLE_URL \
    NEXT_PUBLIC_PILOT_CENTER_LAT=$NEXT_PUBLIC_PILOT_CENTER_LAT \
    NEXT_PUBLIC_PILOT_CENTER_LON=$NEXT_PUBLIC_PILOT_CENTER_LON \
    NEXT_PUBLIC_PILOT_ZOOM=$NEXT_PUBLIC_PILOT_ZOOM \
    NEXT_PUBLIC_PILOT_REGION_NAME=$NEXT_PUBLIC_PILOT_REGION_NAME \
    NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production \
    NEXT_OUTPUT_STANDALONE=1

RUN pnpm --filter @pathable/web build

# -----------------------------------------------------------------------------
# Runtime — standalone server only; no pnpm, no node_modules tree, no sources
# -----------------------------------------------------------------------------
FROM node:26-bookworm-slim AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Debian security updates at build time, for the same reason as the API image:
# the base image's rebuild cadence is not ours, and the scan is.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 pathable \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin pathable

# npm and corepack are never used at runtime — the standalone server is started
# directly with `node apps/web/server.js`. Removing them eliminates every
# fixable HIGH/CRITICAL advisory Trivy reports against this image, all of which
# come from npm's own bundled dependencies (tar, sigstore, ip-address, picomatch,
# brace-expansion) rather than from anything PathAble depends on.
RUN rm -rf /usr/local/lib/node_modules/npm \
           /usr/local/lib/node_modules/corepack \
           /usr/local/bin/npm \
           /usr/local/bin/npx \
           /usr/local/bin/corepack

# `output: 'standalone'` traces exactly the files the server needs. Static assets
# and public/ are not traced and must be copied explicitly.
COPY --from=builder --chown=root:root /repo/apps/web/.next/standalone ./
COPY --from=builder --chown=root:root /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=root:root /repo/apps/web/public ./apps/web/public

USER pathable

EXPOSE 3000

CMD ["node", "apps/web/server.js"]
