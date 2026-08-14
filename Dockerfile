FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock* ./

RUN uv sync --frozen --no-cache

COPY . .
