"""Only accounts marked app_metadata.role = "operator" in Supabase reach the dashboard and the
operator API, and only they get a browser session from a password or a reset."""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.auth import dependencies, router, sessions
from app.auth.dependencies import get_current_user
from app.database import get_supabase
from app.hotels import service
from app.main import create_app
from tests.fakes import NAMED, FakeDB

OPERATOR = SimpleNamespace(user_metadata=NAMED, id="operator-1", app_metadata={"role": "operator"})
NOBODY = SimpleNamespace(user_metadata=NAMED, id="nobody-1", app_metadata={"provider": "email"})
TOKENS = {"access_token": "access", "refresh_token": "refresh", "expires_at": 1_900_000_000}
SESSION = SimpleNamespace(**TOKENS)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Iterator[fakeredis.FakeRedis]:
    redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(sessions, "get_session_store", lambda: redis)
    yield redis


def signed_in_as(user: object, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(service, "list_hotels", lambda db: [])
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_supabase] = lambda: object()
    return TestClient(app, follow_redirects=False)


@pytest.mark.parametrize("path", ["/api/v1/hotels", "/dashboard/hotels"])
def test_an_account_without_the_role_is_refused(path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    assert signed_in_as(NOBODY, monkeypatch).get(path).status_code == 403


@pytest.mark.parametrize("path", ["/api/v1/hotels", "/dashboard/hotels"])
def test_an_operator_gets_in(path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    assert signed_in_as(OPERATOR, monkeypatch).get(path).status_code == 200


class FakeAuth:
    def __init__(self, user: object) -> None:
        self.user = user

    def sign_in_with_password(self, credentials: dict[str, str]) -> SimpleNamespace:
        return SimpleNamespace(user=self.user, session=SESSION)

    def get_user(self, token: str) -> SimpleNamespace:
        return SimpleNamespace(user=self.user)

    def set_session(self, access_token: str, refresh_token: str) -> None:
        pass

    def update_user(self, attributes: dict[str, str]) -> None:
        pass

    def get_session(self) -> SimpleNamespace:
        return SimpleNamespace(**vars(SESSION), user=self.user)


def supabase_with(monkeypatch: pytest.MonkeyPatch, user: object) -> None:
    client = SimpleNamespace(auth=FakeAuth(user))
    monkeypatch.setattr(dependencies, "get_supabase", FakeDB)  # no hotel staff
    monkeypatch.setattr(router, "get_supabase_anon", lambda: client)
    monkeypatch.setattr(router, "create_client", lambda url, key: client)


def sign_in(user: object, monkeypatch: pytest.MonkeyPatch) -> Any:
    supabase_with(monkeypatch, user)
    client = TestClient(create_app(), follow_redirects=False)
    return client.post("/login", data={"email": "a@example.com", "password": "secret-pass"})


def test_a_password_sign_in_without_the_role_gets_no_session(
    monkeypatch: pytest.MonkeyPatch, store: fakeredis.FakeRedis
) -> None:
    response = sign_in(NOBODY, monkeypatch)
    assert response.status_code == 403
    assert router.NO_ACCESS.replace("'", "&#39;") in response.text
    assert store.keys() == []


def test_an_operator_password_sign_in_gets_a_session(
    monkeypatch: pytest.MonkeyPatch, store: fakeredis.FakeRedis
) -> None:
    response = sign_in(OPERATOR, monkeypatch)
    assert (response.status_code, response.headers["location"]) == (303, "/dashboard/hotels")
    assert len(store.keys("web-session:*")) == 1


def test_there_is_no_email_link_sign_in() -> None:
    # Removed: a password, Google, or a reset email get an account in.
    client = TestClient(create_app(), follow_redirects=False)
    assert "email link" not in client.get("/login").text
    assert client.post("/login/magic-link", data={"email": "a@b.invalid"}).status_code == 404
    tokens = {"access_token": "access", "refresh_token": "refresh", "flow_type": "magiclink"}
    assert client.post("/auth/callback/session", json=tokens).status_code == 404


def test_a_reset_without_the_role_changes_the_password_but_signs_nobody_in(
    monkeypatch: pytest.MonkeyPatch, store: fakeredis.FakeRedis
) -> None:
    supabase_with(monkeypatch, NOBODY)
    reset_id = sessions.create_password_reset_session("access", "refresh", None)
    client = TestClient(create_app(), follow_redirects=False)
    client.cookies.set(sessions.PASSWORD_RESET_COOKIE, reset_id)
    response = client.post(
        "/reset-password",
        data={"password": "new-password", "password_confirmation": "new-password"},
    )
    assert response.status_code == 200
    assert "Password updated" in response.text
    assert store.keys() == []
