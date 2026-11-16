# OmniCycler Neware server. Build: podman build -t omnicycler-neware .
# Expects the connector configuration at /config/config.json and keeps its run store in /data
# (set "storage_directory": "/data"). See omnicycler-web/deploy/README.md.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

ENV PATH=/app/.venv/bin:$PATH
VOLUME ["/config", "/data"]
WORKDIR /config
CMD ["connector", "start", "--app", "omnicycler.neware:create_app", "--config-path", "/config/config.json"]
