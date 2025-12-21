FROM python:3.13-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y \
    wget \
    build-essential \
    libssl-dev \
    zlib1g-dev \
    libncurses5-dev \
    libgdbm-dev \
    libnss3-dev \
    libreadline-dev \
    libffi-dev \
    libsqlite3-dev \
    libbz2-dev \
    && rm -rf /var/lib/apt/lists/*

RUN wget https://www.python.org/ftp/python/3.13.1/Python-3.13.1.tgz && \
    tar -xf Python-3.13.1.tgz && \
    cd Python-3.13.1 && \
    ./configure --prefix=/opt/python313t --enable-optimizations --disable-gil && \
    make -j$(nproc) && \
    make install && \
    cd .. && rm -rf Python-3.13.1*

FROM python:3.13-slim

WORKDIR /app

COPY --from=builder /opt/python313t /opt/python313t

ENV PATH="/opt/python313t/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock* ./

RUN uv sync --frozen --no-cache

COPY . .

EXPOSE 9001

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9001", "--workers", "8"]