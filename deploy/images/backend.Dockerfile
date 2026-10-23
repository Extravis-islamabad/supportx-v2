# syntax=docker/dockerfile:1.10
# SupportX backend image (WP-014): one image, several roles chosen by the command:
#   api        uvicorn app.main:create_app --factory          (Core API + BFF, D-009)
#   relay      python -m workers.outbox_relay
#   consumers  python -m workers.consumers
#   fanout     python -m workers.realtime_fanout
#   migrate    python -m tooling.db_bootstrap ... && alembic upgrade head   (Helm hook Job)
#
# INTERNAL / DEV BUILD (D-038, decision D8): plain CPython, source included. It must never be
# given to a customer; customer bundles require the Nuitka-compiled build (ADR-009, WP-013).
ARG PYTHON_IMAGE=python:3.12.15-slim-trixie
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.19

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
# Dependencies first: this layer is reused until the lockfile changes.
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

FROM ${PYTHON_IMAGE} AS runtime
ARG VERSION=0.0.0-dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="supportx-backend" \
      org.opencontainers.image.description="SupportX v2 API and workers. INTERNAL/DEV BUILD - not for customer distribution (Nuitka build required, ADR-009)." \
      org.opencontainers.image.vendor="Extravis" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.source="https://github.com/devhat-pm/supportx-v2" \
      com.extravis.supportx.distribution="internal-dev-only"
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SUPPORTX_DISTRIBUTION=internal-dev-only
RUN groupadd --system --gid 10001 supportx \
 && useradd --system --uid 10001 --gid supportx --home-dir /app --shell /usr/sbin/nologin supportx
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --chown=root:root backend/alembic.ini ./
COPY --chown=root:root backend/app ./app
COPY --chown=root:root backend/workers ./workers
COPY --chown=root:root backend/migrations ./migrations
COPY --chown=root:root backend/tooling ./tooling
# Byte-compile at build time: the root filesystem is read-only at run time.
RUN python -m compileall -q app workers migrations tooling
USER 10001:10001
EXPOSE 8000 9464
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
