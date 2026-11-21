# syntax=docker/dockerfile:1.6
# Local Home Assistant Supervisor build, no GitHub Actions or fork GHCR needed.
# Pin the source commit so every 0.18.2.post1 installation is reproducible.
FROM node:20-bookworm AS simplyq-source

ARG SOURCE_COMMIT=7f79b8b31742b51b36380e47c1485480a9d9c9c3

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /src \
    && curl --fail --location --silent --show-error --retry 3 \
       "https://codeload.github.com/michlimek/frigate/tar.gz/${SOURCE_COMMIT}" \
       -o /tmp/frigate-src.tar.gz \
    && tar -xzf /tmp/frigate-src.tar.gz -C /src --strip-components=1 \
    && rm /tmp/frigate-src.tar.gz

WORKDIR /src/web
RUN npm install

RUN printf 'VITE_GIT_COMMIT_HASH=%s\n' "$(printf '%s' "$SOURCE_COMMIT" | cut -c 1-7)" > .env \
    && npm run build \
    && mv dist/BASE_PATH/monacoeditorwork/* dist/assets/ \
    && rm -rf dist/BASE_PATH

RUN printf 'VERSION = "0.18.2.post1-%s"\n' \
      "$(printf '%s' "$SOURCE_COMMIT" | cut -c 1-7)" > /src/frigate/version.py

# Reuse official Frigate 0.18.2 runtime (ffmpeg, detectors, s6, nginx).
# Replace complete application code, migrations, and compiled web UI.
FROM ghcr.io/blakeblackshear/frigate:0.18.2

LABEL org.opencontainers.image.source="https://github.com/michlimek/frigate" \
      org.opencontainers.image.version="0.18.2.post1" \
      org.opencontainers.image.description="SimplyQ Frigate PTZ vehicle visit grouping"

COPY --from=simplyq-source /src/frigate/ /opt/frigate/frigate/
COPY --from=simplyq-source /src/migrations/ /opt/frigate/migrations/
COPY --from=simplyq-source /src/web/dist/ /opt/frigate/web/
