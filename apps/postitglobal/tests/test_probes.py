"""Kubernetes probes: /healthz says the process answers; /readyz says it can serve, which
here means Redis (operator sessions) answers in time."""

import time

import fakeredis
import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app import main
from app.auth import sessions
from app.main import create_app


def test_liveness_needs_nothing() -> None:
    client = TestClient(create_app())
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/health").json() == {"status": "ok"}  # Railway's, until 5.9


def test_ready_when_redis_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sessions, "get_session_store", fakeredis.FakeRedis)
    response = TestClient(create_app()).get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


class DownRedis:
    def ping(self) -> bool:
        raise RedisConnectionError("Connection refused")


class SlowRedis:
    def ping(self) -> bool:
        time.sleep(0.5)
        return True


@pytest.mark.parametrize("store", [DownRedis, SlowRedis])
def test_not_ready_when_redis_is_down_or_slow(
    monkeypatch: pytest.MonkeyPatch, store: type[object]
) -> None:
    monkeypatch.setattr(sessions, "get_session_store", store)
    monkeypatch.setattr(main, "READY_TIMEOUT_SECONDS", 0.1)
    client = TestClient(create_app())
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"detail": "not ready: Redis"}
    assert client.get("/healthz").status_code == 200  # alive all the same
