# syntax=docker/dockerfile:1.10
# SupportX web image (WP-014): the console at / and the portal at /portal/ as static files.
# Everything is same-origin (D-009): /api and /connection are routed to other services by the
# gateway, so the bundles need no runtime configuration.
# INTERNAL / DEV BUILD (D-038): not for customer distribution until the release pipeline (WP-014c).
ARG NODE_IMAGE=node:24.22.1-alpine3.24
ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.30.6-alpine3.24

FROM ${NODE_IMAGE} AS build
WORKDIR /src
RUN corepack enable
COPY frontend/ ./frontend/
COPY tsconfig.base.json .prettierrc.json ./
WORKDIR /src/frontend
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    CI=true pnpm install --frozen-lockfile \
 && pnpm --filter @supportx/console --filter @supportx/portal build

FROM ${NGINX_IMAGE} AS runtime
ARG VERSION=0.0.0-dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="supportx-web" \
      org.opencontainers.image.description="SupportX v2 console and portal (static). INTERNAL/DEV BUILD - not for customer distribution." \
      org.opencontainers.image.vendor="Extravis" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.source="https://github.com/devhat-pm/supportx-v2" \
      com.extravis.supportx.distribution="internal-dev-only"
# Security fixes published after the base image (e.g. brotli-libs CVE-2026-111497), then back to
# the unprivileged user below. The image gate fails on fixable HIGH/CRITICAL findings.
USER root
RUN apk upgrade --no-cache
COPY deploy/images/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/frontend/apps/console/dist /usr/share/nginx/html/
COPY --from=build /src/frontend/apps/portal/dist /usr/share/nginx/html/portal/
# The unprivileged base already runs as nginx (101); stated so scanners and readers see it.
USER 101
EXPOSE 8080
