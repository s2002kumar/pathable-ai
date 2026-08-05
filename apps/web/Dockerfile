# syntax=docker/dockerfile:1.7
#
# PathAble web image. Build context is the repository root:
#   docker build -f apps/web/Dockerfile .

FROM node:22-bookworm-slim AS base
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
FROM node:22-bookworm-slim AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN groupadd --gid 10001 pathable \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin pathable

# `output: 'standalone'` traces exactly the files the server needs. Static assets
# and public/ are not traced and must be copied explicitly.
COPY --from=builder --chown=root:root /repo/apps/web/.next/standalone ./
COPY --from=builder --chown=root:root /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=root:root /repo/apps/web/public ./apps/web/public

USER pathable

EXPOSE 3000

CMD ["node", "apps/web/server.js"]
