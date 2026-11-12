"""Error tracking: off without SENTRY_DSN; with one, an unhandled error becomes one event
that carries the request ID and none of the request's secrets."""

from collections.abc import Iterator
from typing import Any

import pytest
import sentry_sdk
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import HttpTransport

from app.config import get_settings
from app.main import create_app
from app.observability import REQUEST_ID_HEADER

DSN = "https://public-key@errors.invalid/1"  # never reached: the transport below is a fake


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """SENTRY_DSN is set, and what the SDK would send is collected here instead. Afterwards
    the SDK is off again, so no other test sees it."""
    sent: list[dict[str, Any]] = []

    def collect(self: HttpTransport, envelope: Envelope) -> None:
        if (event := envelope.get_event()) is not None:
            sent.append(dict(event))

    monkeypatch.setattr(HttpTransport, "capture_envelope", collect)
    monkeypatch.setenv("SENTRY_DSN", DSN)
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "staging")
    monkeypatch.setenv("SENTRY_RELEASE", "aipostit@1.2.3")
    get_settings.cache_clear()
    yield sent
    sentry_sdk.get_client().close()
    sentry_sdk.get_global_scope().set_client(None)


def failing_app() -> FastAPI:
    app = create_app()

    @app.post("/boom")
    def boom() -> None:
        raise RuntimeError("the kitchen is on fire")

    return app


def test_without_a_dsn_nothing_is_initialised() -> None:
    create_app()
    assert not sentry_sdk.is_initialized()


def test_an_unhandled_error_is_one_event_with_its_request_id(events: list[dict[str, Any]]) -> None:
    client = TestClient(failing_app(), raise_server_exceptions=False)
    response = client.post("/boom", headers={REQUEST_ID_HEADER: "req-42"})

    assert response.status_code == 500
    (event,) = events
    assert event["exception"]["values"][-1]["value"] == "the kitchen is on fire"
    assert event["tags"]["request_id"] == "req-42"
    assert event["environment"] == "staging" and event["release"] == "aipostit@1.2.3"
    assert event["transaction"] == "/boom"


def test_an_event_carries_no_secrets_of_the_request(events: list[dict[str, Any]]) -> None:
    client = TestClient(failing_app(), raise_server_exceptions=False)
    client.post(
        "/boom?code=oauth-code-value",
        headers={"Authorization": "Bearer supabase-jwt-value", "Cookie": "session=cookie-value"},
        data={"email": "staff@hotel.example", "password": "form-password-value"},
    )

    (event,) = events
    sent = repr(event)
    for secret in (
        "supabase-jwt-value",
        "cookie-value",
        "staff@hotel.example",
        "form-password-value",
        "oauth-code-value",
    ):
        assert secret not in sent
    assert "vars" not in event["exception"]["values"][-1]["stacktrace"]["frames"][-1]


def test_no_personal_data_by_default_and_no_tracing(events: list[dict[str, Any]]) -> None:
    create_app()
    client = sentry_sdk.get_client()
    assert client.should_send_default_pii() is False
    assert client.options["traces_sample_rate"] == 0.0


def test_the_worker_tracks_errors_too(
    events: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs import tasks

    monkeypatch.setattr(tasks, "settings", get_settings())
    tasks._error_tracking()
    assert sentry_sdk.is_initialized()
    assert sentry_sdk.get_client().get_integration("celery") is not None
