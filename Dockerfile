FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/app/.venv/bin:$PATH"

# Install from PyPI so builds do not depend on GHCR's blob storage.
ARG UV_VERSION=0.11.16
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
    --retries 5 --timeout 60 "uv==${UV_VERSION}"

COPY pyproject.toml uv.lock* ./

# Keep completed downloads across builds and tolerate transient package-CDN failures.
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_HTTP_RETRIES=10 UV_HTTP_TIMEOUT=120 UV_HTTP_CONNECT_TIMEOUT=30 \
    UV_CONCURRENT_DOWNLOADS=4 UV_LINK_MODE=copy \
    uv sync --frozen

COPY . .
