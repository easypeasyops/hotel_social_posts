"""The probes the platform's service chart sends to port 8000: /healthz while the process
runs (liveness), /readyz while the Socket Mode connection to Slack is up (readiness). The bot
serves nothing else; nothing routes to this port."""

import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8000


def serve(connected: Callable[[], bool], port: int = PORT) -> ThreadingHTTPServer:
    """Answers the probes from a daemon thread; returns the server (to stop it in tests)."""

    class Probes(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            match self.path:
                case "/healthz":
                    self._answer(200, "ok")
                case "/readyz" if connected():
                    self._answer(200, "ok")
                case "/readyz":
                    self._answer(503, "not ready: no Slack connection")
                case _:
                    self._answer(404, "not found")

        def _answer(self, status: int, text: str) -> None:
            body = text.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass  # a probe every few seconds would drown the command log

    server = ThreadingHTTPServer(("0.0.0.0", port), Probes)  # noqa: S104  # the kubelet probes the pod IP
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
