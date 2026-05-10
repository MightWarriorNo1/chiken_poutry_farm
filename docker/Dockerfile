# Multi-arch (amd64 + arm64) base image for the EdgeBox runtime.
# For Jetson with CUDA acceleration, use Dockerfile.jetson instead.

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# OpenCV needs these even with the headless wheel.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgl1 \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first to leverage Docker layer cache.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install ".[ai,sensors]"

# Models are mounted as a volume in production; copy here for self-contained builds.
COPY models ./models
COPY contracts ./contracts

# tini reaps zombies and forwards signals — important for clean shutdown.
ENTRYPOINT ["/usr/bin/tini", "--", "prosper-edge"]
