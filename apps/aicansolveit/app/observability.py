"""Logs (platform plan 5.3): one JSON object per line on stdout, each carrying the request
ID of the request it belongs to, so a request's lines can be found together. The platform
collects stdout; nothing writes log files. Modelled on shortly's observability module.
"""

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Final

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


def _route_template(scope: Scope) -> str:
    # The route's template (/api/v1/hotels/{hotel_id}), never the raw path: raw paths would
    # put IDs in every line's route field and make lines impossible to group.
    path = getattr(scope.get("route"), "path", None)
    return path if isinstance(path, str) else "unmatched"


class RequestContextMiddleware:
    """Pure ASGI middleware: a request ID for every request (echoed in the response's
    X-Request-ID header) and one access log line when it ends."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

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
            access_log.log(
                logging.DEBUG if scope["path"] in QUIET_PATHS else logging.INFO,
                "request",
                extra={
                    "method": scope["method"],
                    "route": _route_template(scope),
                    "status": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
            request_id_var.reset(token)
