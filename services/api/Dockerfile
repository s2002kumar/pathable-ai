# syntax=docker/dockerfile:1.7
#
# PathAble API image. Build context is the repository root:
#   docker build -f services/api/Dockerfile .

# uv is copied from its own published image rather than curl-installed, which
# keeps the version explicit and avoids a network fetch inside the build.
FROM ghcr.io/astral-sh/uv:0.12.3 AS uv

# -----------------------------------------------------------------------------
# Builder — resolve and install dependencies into a self-contained virtualenv
# -----------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS builder

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Manifests first: this layer is cached until the dependency set actually
# changes, so editing application code does not re-resolve the world.
COPY services/api/pyproject.toml services/api/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# --no-editable installs a real copy into the venv, so the runtime stage needs
# no source tree and no path shims.
COPY services/api/src ./src
COPY services/api/README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# -----------------------------------------------------------------------------
# Runtime — no build tools, no dev dependencies, no uv
# -----------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

# 10001 is outside the range typical distro packages claim, so the mapping stays
# predictable if a volume is ever shared with the host.
RUN groupadd --gid 10001 pathable \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin pathable

WORKDIR /app

COPY --from=builder --chown=root:root /app/.venv /app/.venv

# Alembic assets are not part of the installed wheel, so they are copied
# explicitly. Nothing else from the repository ends up in the image.
COPY --chown=root:root services/api/alembic.ini ./alembic.ini
COPY --chown=root:root services/api/migrations ./migrations
COPY --chown=root:root infra/docker/api-entrypoint.sh /usr/local/bin/api-entrypoint.sh

RUN chmod 0755 /usr/local/bin/api-entrypoint.sh

# Deliberately no .env and no credentials in the image: every secret arrives at
# run time through the environment.
USER pathable

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/api-entrypoint.sh"]

# Started through the package entry point rather than the uvicorn CLI so there is
# a single supported startup path across Linux containers and native Windows
# development. Host and port come from the validated settings (API_HOST/API_PORT),
# which Compose supplies.
CMD ["python", "-m", "pathable_api"]
