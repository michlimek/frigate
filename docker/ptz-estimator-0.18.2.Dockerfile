# Minimal, version-pinned patch on top of the official stable Frigate 0.18.2.
# Do not inherit the 0.19 development image or rebuild unrelated dependencies.
FROM ghcr.io/blakeblackshear/frigate:0.18.2

LABEL org.opencontainers.image.version="0.18.2-ptz-estimator-test" \
      org.opencontainers.image.description="Frigate 0.18.2 with corrected PTZ movement-time prediction"

COPY frigate/ptz/autotrack.py /opt/frigate/frigate/ptz/autotrack.py

# Keep the base image ENTRYPOINT/CMD, libraries and camera runtime unchanged.
