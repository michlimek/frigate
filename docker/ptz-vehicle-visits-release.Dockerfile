# syntax=docker/dockerfile:1.6
# Build only on the external release runner. NEVER run this build on HA OS.
FROM --platform=$BUILDPLATFORM node:20-bookworm AS web-build
ENV NODE_OPTIONS=--max-old-space-size=4096
WORKDIR /work
COPY web/package.json web/package-lock.json ./
COPY web/patches/ patches/
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build \
    && mv dist/BASE_PATH/monacoeditorwork/* dist/assets/ \
    && rm -rf dist/BASE_PATH

# Keep Frigate's upstream hardware/runtime dependencies; ship our complete code.
FROM ghcr.io/blakeblackshear/frigate:0.18.2
LABEL org.opencontainers.image.source="https://github.com/michlimek/frigate" \
      org.opencontainers.image.version="0.18.2.post4"
WORKDIR /opt/frigate
COPY frigate/ frigate/
COPY migrations/ migrations/
COPY --from=web-build /work/dist/ web/
