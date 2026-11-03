# Dependencies from uv.lock, the project's one source of truth (platform plan 5.2). The
# platform's image rules (pinned digests, non-root, two stages) come in 5.3.
FROM python:3.15-slim

# The base image ships pip (with its own vendored urllib3, msgpack, ...) and ensurepip's
# bundled wheels (setuptools). uv installs the dependencies and nothing installs at run
# time, so they are attack surface and scanner findings only. Remove them, as shortly does.
RUN python -m pip uninstall --yes --quiet pip \
 && rm -rf /usr/local/lib/python3.*/ensurepip

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv
# The virtualenv lives outside /app, so compose's source mount (.:/app) doesn't hide it.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

# Install dependencies
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

# Copy source (.dockerignore keeps .env, tests and caches out)
COPY . .

# Default: run the FastAPI app
# Override with CMD in Railway for the worker service
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
