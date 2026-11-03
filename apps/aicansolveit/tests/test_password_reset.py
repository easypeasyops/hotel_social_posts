"""The password-reset link: Supabase's recovery redirect lands on /auth/callback, whose page
posts the tokens to /auth/callback/recovery; that checks them with Supabase, keeps them in
Redis for 15 minutes and sets a cookie for /reset-password."""

import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.auth import router, sessions
from app.main import create_app

TOKENS = {"access_token": "access", "refresh_token": "refresh", "expires_at": 1_900_000_000}


class FakeAuth:
    def __init__(self, user: object) -> None:
        self.user = user
        self.tokens: list[str] = []

    def get_user(self, token: str) -> SimpleNamespace:
        self.tokens.append(token)
        return SimpleNamespace(user=self.user)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Iterator[fakeredis.FakeRedis]:
    redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(sessions, "get_session_store", lambda: redis)
    yield redis


def supabase_with(monkeypatch: pytest.MonkeyPatch, user: object) -> FakeAuth:
    auth = FakeAuth(user)
    monkeypatch.setattr(router, "get_supabase_anon", lambda: SimpleNamespace(auth=auth))
    return auth


def post_recovery(**overrides: Any) -> Any:
    client = TestClient(create_app(), follow_redirects=False)
    return client.post(
        "/auth/callback/recovery", json={**TOKENS, "flow_type": "recovery", **overrides}
    )


def test_a_valid_link_opens_the_reset_form(
    monkeypatch: pytest.MonkeyPatch, store: fakeredis.FakeRedis
) -> None:
    auth = supabase_with(monkeypatch, user=object())
    response = post_recovery()

    assert response.status_code == 303
    assert response.headers["location"] == "/reset-password"
    assert auth.tokens == ["access"]
    reset_id = response.cookies[sessions.PASSWORD_RESET_COOKIE]
    key = f"password-reset:{reset_id}"
    assert json.loads(str(store.get(key))) == TOKENS
    ttl = int(store.ttl(key))  # type: ignore[arg-type]  # redis-py types sync and async alike
    assert 0 < ttl <= sessions.PASSWORD_RESET_TTL_SECONDS


def test_a_link_without_a_user_is_refused(
    monkeypatch: pytest.MonkeyPatch, store: fakeredis.FakeRedis
) -> None:
    supabase_with(monkeypatch, user=None)
    assert post_recovery().status_code == 401
    assert store.keys() == []


def test_a_sign_in_link_is_not_a_reset_link(
    monkeypatch: pytest.MonkeyPatch, store: fakeredis.FakeRedis
) -> None:
    auth = supabase_with(monkeypatch, user=object())
    assert post_recovery(flow_type="magiclink").status_code == 400
    assert auth.tokens == []
