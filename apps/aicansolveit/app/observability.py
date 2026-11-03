"""Logs and metrics (platform plan 5.3), modelled on shortly's observability module.

* Logs: one JSON object per line on stdout, each carrying the request ID of the request it
  belongs to, so a request's lines can be found together. The platform collects stdout;
  nothing writes log files.
* Metrics: request counts and latencies (RED), labelled by route template, never the raw
  path: raw paths would make one time series per hotel or draft ID. Served on their own
  port (9100), so the public port carries none of it. The names are shortly's, so the
  platform's SLO rules and dashboards read aicansolveit the same way.
"""

import json
import logging
import re
import sys
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Final

from prometheus_client import CollectorRegistry, Counter, Histogram, start_http_server
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER: Final = "x-request-id"
# A caller's request ID is kept only if it's short and plain: anything else could inject
# log lines or bloat log storage, so it's replaced.
_VALID_REQUEST_ID: Final = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# Probes and scrapes are frequent and uninteresting: logged at DEBUG, not INFO.
QUIET_PATHS: Final = frozenset({"/healthz", "/health", "/readyz", "/metrics"})

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

access_log = logging.getLogger("aicansolveit.access")

_STANDARD_ATTRS: Final = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()
    | {"message", "asctime", "color_message"}  # uvicorn adds an ANSI-colored copy of msg
)


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Fields passed with `extra=` become top-level keys."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if (request_id := request_id_var.get()) is not None:
            entry["request_id"] = request_id
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Everything (ours, uvicorn's, Celery's, the HTTP clients') through one stdout handler."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if json_output else logging.Formatter("%(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # uvicorn installs its own handlers: remove them so its lines become JSON too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    # Replaced by the access log below, which has route templates and request IDs.
    logging.getLogger("uvicorn.access").disabled = True
    # httpx logs every request URL at INFO, and a Supabase URL is all there is to see.
    logging.getLogger("httpx").setLevel(logging.WARNING)


class Metrics:
    """The app's metrics, on a registry of their own (one per app keeps tests isolated)."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self.requests = Counter(
            "http_requests",
            "HTTP requests by route template and status.",
            ["method", "route", "status"],
            registry=self.registry,
        )
        self.latency = Histogram(
            "http_request_duration_seconds",
            "HTTP request latency.",
            ["method", "route"],
            # Pages render in tens of milliseconds; Supabase round trips push some to 1 s.
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
            registry=self.registry,
        )


def serve_metrics(metrics: Metrics, port: int) -> Callable[[], None]:
    """Serve /metrics on its own port, in its own thread; returns the function that stops it.
    Its own thread also means a scrape never waits behind request work."""
    server, thread = start_http_server(port, registry=metrics.registry)

    def stop() -> None:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    return stop


def _route_template(scope: Scope) -> str:
    # The route's template (/api/v1/hotels/{hotel_id}), never the raw path: raw paths would
    # put IDs in every line's route field and make lines impossible to group.
    path = getattr(scope.get("route"), "path", None)
    return path if isinstance(path, str) else "unmatched"


class RequestContextMiddleware:
    """Pure ASGI middleware: a request ID for every request (echoed in the response's
    X-Request-ID header), and when it ends its RED metrics and one access log line."""

    def __init__(self, app: ASGIApp, metrics: Metrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER.encode(), b"").decode("latin-1")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        status = 500  # what the client sees if the app raises before responding
        start = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            elapsed = time.perf_counter() - start
            method, route = scope["method"], _route_template(scope)
            self.metrics.requests.labels(method, route, str(status)).inc()
            self.metrics.latency.labels(method, route).observe(elapsed)
            access_log.log(
                logging.DEBUG if scope["path"] in QUIET_PATHS else logging.INFO,
                "request",
                extra={
                    "method": method,
                    "route": route,
                    "status": status,
                    "duration_ms": round(elapsed * 1000, 2),
                },
            )
            request_id_var.reset(token)
