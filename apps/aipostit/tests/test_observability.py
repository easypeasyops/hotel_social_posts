"""Logs: one JSON object per line, each line of a request carrying its request ID, and one
access log line per request with the route template, never the raw path."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.observability import REQUEST_ID_HEADER, JsonFormatter, request_id_var


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_a_log_line_is_one_json_object_with_its_extras() -> None:
    token = request_id_var.set("req-1")
    try:
        record = logging.LogRecord(
            "app.x", logging.WARNING, "", 0, "translation failed", None, None
        )
        record.draft_id = "draft-1"
        line = JsonFormatter().format(record)
    finally:
        request_id_var.reset(token)

    entry = json.loads(line)
    assert "\n" not in line
    assert entry["level"] == "warning" and entry["logger"] == "app.x"
    assert entry["msg"] == "translation failed"
    assert entry["request_id"] == "req-1"
    assert entry["draft_id"] == "draft-1"


def test_every_response_carries_a_request_id(client: TestClient) -> None:
    first = client.get("/healthz").headers[REQUEST_ID_HEADER]
    second = client.get("/healthz").headers[REQUEST_ID_HEADER]
    assert len(first) == 32 and first != second


def test_a_callers_plain_request_id_is_kept(client: TestClient) -> None:
    response = client.get("/healthz", headers={REQUEST_ID_HEADER: "abc-123"})
    assert response.headers[REQUEST_ID_HEADER] == "abc-123"


@pytest.mark.parametrize("bad", ["a b", "x" * 65, "line\\nbreak", "<script>"])
def test_an_unsafe_request_id_is_replaced(client: TestClient, bad: str) -> None:
    response = client.get("/healthz", headers={REQUEST_ID_HEADER: bad})
    assert response.headers[REQUEST_ID_HEADER] != bad


def test_the_access_log_names_the_route_not_the_path(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="aipostit.access"):
        client.get("/upload-missing/x")  # unmatched
        client.get("/login")
    lines = [r for r in caplog.records if r.name == "aipostit.access"]
    assert [(r.route, r.status) for r in lines] == [("unmatched", 404), ("/login", 200)]  # type: ignore[attr-defined]
    assert all(r.levelno == logging.INFO and r.duration_ms >= 0 for r in lines)  # type: ignore[attr-defined]


def test_probes_are_logged_quietly(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="aipostit.access"):
        client.get("/healthz")
    (line,) = [r for r in caplog.records if r.name == "aipostit.access"]
    assert line.levelno == logging.DEBUG
