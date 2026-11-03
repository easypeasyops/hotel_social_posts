"""Request metrics: counts and latencies by route template and status, on their own port."""

import socket
import urllib.request

import pytest
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from app.main import create_app
from app.observability import Metrics, serve_metrics


def scrape(metrics: Metrics) -> str:
    return generate_latest(metrics.registry).decode()


def test_requests_are_counted_by_route_template_and_status() -> None:
    app = create_app()
    client = TestClient(app)
    client.get("/login")
    client.get("/login")
    client.get("/upload/some-hotel-slug-that-is-not-a-route/x")  # a 404, no route

    text = scrape(app.state.metrics)
    assert 'http_requests_total{method="GET",route="/login",status="200"} 2.0' in text
    assert 'http_requests_total{method="GET",route="unmatched",status="404"} 1.0' in text
    assert 'http_request_duration_seconds_count{method="GET",route="/login"} 2.0' in text
    assert "some-hotel-slug" not in text  # never the raw path


def test_metrics_are_not_on_the_public_port() -> None:
    assert TestClient(create_app()).get("/metrics").status_code == 404


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def test_metrics_are_served_on_their_own_port() -> None:
    metrics = Metrics()
    metrics.requests.labels("GET", "/login", "200").inc()
    port = free_port()
    stop = serve_metrics(metrics, port)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5) as response:
            body = response.read().decode()
    finally:
        stop()
    assert 'http_requests_total{method="GET",route="/login",status="200"} 1.0' in body


def test_the_app_starts_and_stops_its_metrics_server(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    port = free_port()
    monkeypatch.setenv("METRICS_PORT", str(port))
    get_settings.cache_clear()
    with TestClient(create_app()) as client:  # runs the lifespan
        client.get("/login")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5) as response:
            assert 'route="/login"' in response.read().decode()
    # The server stopped with the app: nothing answers on the port any more. (Not "the port
    # can be bound again": the closed scrape connection can hold it in TIME_WAIT.)
    with pytest.raises(ConnectionRefusedError), socket.create_connection(("127.0.0.1", port), 1):
        pass
