"""Continue with Google: /login/google keeps a PKCE verifier in a cookie and sends the browser
to Supabase; /auth/callback/google trades the code and that verifier for a session, which only
an operator gets."""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import fakeredis
import pytest
from fastapi.testclient import TestClient
from supabase_auth.errors import AuthApiError
from supabase_auth.helpers import generate_pkce_challenge

from app.auth import dependencies, google, sessions
from app.config import get_settings
from app.main import create_app
from tests.fakes import FakeDB

OPERATOR = SimpleNamespace(id="operator-1", app_metadata={"role": "operator"})
NOBODY = SimpleNamespace(id="nobody-1", app_metadata={"provider": "google"})
TOKENS = {"access_token": "access", "refresh_token": "refresh", "expires_at": 1_900_000_000}


@pytest.fixture(autouse=True)
def enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_SIGN_IN", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.example.com")


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Iterator[fakeredis.FakeRedis]:
    redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(sessions, "get_session_store", lambda: redis)
    yield redis


class FakeAuth:
    def __init__(self, user: object, error: Exception | None = None) -> None:
        self.user = user
        self.error = error
        self.exchanges: list[dict[str, str]] = []

    def exchange_code_for_session(self, params: dict[str, str]) -> SimpleNamespace:
        self.exchanges.append(params)
        if self.error:
            raise self.error
        return SimpleNamespace(user=self.user, session=SimpleNamespace(**TOKENS))


def supabase_with(
    monkeypatch: pytest.MonkeyPatch, user: object, error: Exception | None = None
) -> FakeAuth:
    auth = FakeAuth(user, error)
    monkeypatch.setattr(dependencies, "get_supabase", FakeDB)  # no hotel staff
    monkeypatch.setattr(google, "get_supabase_anon", lambda: SimpleNamespace(auth=auth))
    return auth


def client() -> TestClient:
    return TestClient(create_app(), base_url="https://app.example.com", follow_redirects=False)


def come_back(browser: TestClient, **query: str) -> Any:
    return browser.get(google.CALLBACK_PATH, params=query)


def test_the_button_shows_only_when_switched_on(monkeypatch: pytest.MonkeyPatch) -> None:
    assert 'href="/login/google"' in client().get("/login").text
    monkeypatch.setenv("GOOGLE_SIGN_IN", "false")
    get_settings.cache_clear()
    assert 'href="/login/google"' not in client().get("/login").text
    assert client().get("/login/google").status_code == 404


def test_the_start_sends_a_pkce_challenge_for_the_verifier_it_keeps() -> None:
    response = client().get("/login/google")

    assert response.status_code == 303
    url = urlsplit(response.headers["location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://supabase.invalid/auth/v1/authorize"
    query = {key: values[0] for key, values in parse_qs(url.query).items()}
    verifier = response.cookies[google.VERIFIER_COOKIE]
    assert query == {
        "provider": "google",
        "redirect_to": "https://app.example.com/auth/callback/google",
        "code_challenge": generate_pkce_challenge(verifier),
        "code_challenge_method": "s256",
    }
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert "path=/auth/callback/google" in cookie


def test_an_operator_comes_back_signed_in(
    monkeypatch: pytest.MonkeyPatch, store: fakeredis.FakeRedis
) -> None:
    auth = supabase_with(monkeypatch, OPERATOR)
    browser = client()
    verifier = browser.get("/login/google").cookies[google.VERIFIER_COOKIE]
    response = come_back(browser, code="one-time-code")

    assert response.status_code == 200
    assert 'href="/dashboard/hotels"' in response.text
    assert auth.exchanges == [
        {
            "auth_code": "one-time-code",
            "code_verifier": verifier,
            "redirect_to": "https://app.example.com/auth/callback/google",
        }
    ]
    session_id = response.cookies[sessions.SESSION_COOKIE]
    assert store.get(f"web-session:{session_id}") is not None
    assert response.headers["cache-control"] == "no-store"


def test_an_account_without_the_role_gets_no_session(
    monkeypatch: pytest.MonkeyPatch, store: fakeredis.FakeRedis
) -> None:
    supabase_with(monkeypatch, NOBODY)
    browser = client()
    browser.get("/login/google")
    response = come_back(browser, code="one-time-code")

    assert response.status_code == 403
    assert "have access to postitglobal" in response.text
    assert store.keys() == []


def test_an_address_without_an_account_is_told_so(monkeypatch: pytest.MonkeyPatch) -> None:
    auth = supabase_with(monkeypatch, OPERATOR)
    response = come_back(client(), error="access_denied", error_code="signup_disabled")
    assert response.status_code == 403
    assert "no postitglobal account for that Google address" in response.text
    assert auth.exchanges == []


def test_a_code_without_the_verifier_cookie_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Someone else's code pushed into this browser (login CSRF) has no verifier here.
    auth = supabase_with(monkeypatch, OPERATOR)
    response = come_back(client(), code="someone-elses-code")
    assert response.status_code == 400
    assert auth.exchanges == []


@pytest.mark.parametrize(
    ("error", "status"),
    [(AuthApiError("invalid flow state", 400, "flow_state_not_found"), 401), (OSError(), 502)],
)
def test_a_failed_exchange_says_so(
    error: Exception, status: int, monkeypatch: pytest.MonkeyPatch, store: fakeredis.FakeRedis
) -> None:
    supabase_with(monkeypatch, OPERATOR, error)
    browser = client()
    browser.get("/login/google")
    assert come_back(browser, code="one-time-code").status_code == status
    assert store.keys() == []
