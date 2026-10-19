ARG WAHA_IMAGE=devlikeapro/waha:gows-2026.9.1@sha256:d2056b8dec41b218b54f431b8b4eb7d148346d530bb3658295ecb882944e9a18
FROM ${WAHA_IMAGE}

# Same volume ownership setup used by Orbia.
USER root
RUN mkdir -p /app/.sessions /app/.media \
    && chown 1000:1000 /app/.sessions /app/.media
USER 1000:1000
