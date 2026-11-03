# syntax=docker/dockerfile:1
#
# Two stages, as shortly's image (platform plan 5.3): a builder with uv that installs the
# locked dependencies, and a runtime that receives only the finished virtualenv and the
# code. Build tools never reach production.
#
# Base images are pinned by digest (tags move); Dependabot bumps the digests. Keep the two
# FROM lines identical so builder and runtime share one Python.

# ---------------------------------------------------------------------------- builder
FROM python:3.15-slim-trixie@sha256:94d3426f1def7db4a106a232ac121bfd975393e5dfd40a619b955fae45fe7913 AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 /uv /bin/uv

# The virtualenv lives outside /app, so compose's source mount (.:/app) doesn't hide it.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# Third-party dependencies only: this layer is rebuilt only when the lockfile changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=.python-version,target=.python-version \
    uv sync --locked --no-dev --no-install-project

# ---------------------------------------------------------------------------- runtime
FROM python:3.15-slim-trixie@sha256:94d3426f1def7db4a106a232ac121bfd975393e5dfd40a619b955fae45fe7913 AS runtime

# Fixed, non-root UID/GID: predictable file ownership and Kubernetes `runAsNonRoot`.
# The base image's pip (with its vendored urllib3, msgpack, ...) and ensurepip's bundled
# wheels go: nothing installs at run time, so they are attack surface and scanner findings.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
 && python -m pip uninstall --yes --quiet pip \
 && rm -rf /usr/local/lib/python3.*/ensurepip

WORKDIR /app

# Code and dependencies stay owned by root and only readable by `app`: a compromised
# process can't rewrite them. (.dockerignore keeps .env, tests and caches out.)
COPY --from=builder /opt/venv /opt/venv
COPY app ./app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app
EXPOSE 8000 9100

# For `docker run` and compose. Kubernetes ignores it and uses its own probes.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

# Exec form: uvicorn is PID 1 and receives SIGTERM itself, so requests in flight finish
# before it exits (a shell in front would swallow the signal). The worker runs the same
# image with its own command: celery -A app.jobs.tasks.celery_app worker.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--timeout-graceful-shutdown", "20", \
     "--no-access-log", \
     "--no-server-header"]
