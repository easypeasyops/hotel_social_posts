"""/forgot-password asks Supabase to email a recovery link that lands on /auth/callback, and
answers the same whether or not the address has an account."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from supabase_auth.errors import AuthApiError

from app.auth import router
from app.main import create_app


class FakeAuth:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def reset_password_for_email(self, email: str, options: dict[str, Any]) -> None:
        self.requests.append((email, options))
        if self.error:
            raise self.error


def supabase_with(monkeypatch: pytest.MonkeyPatch, error: Exception | None = None) -> FakeAuth:
    auth = FakeAuth(error)
    monkeypatch.setattr(router, "get_supabase_anon", lambda: SimpleNamespace(auth=auth))
    return auth


def request_reset(email: str = "ops@example.com") -> Any:
    return TestClient(create_app()).post("/forgot-password", data={"email": email})


def test_the_sign_in_page_links_to_the_forgot_password_page() -> None:
    login = TestClient(create_app()).get("/login")
    assert 'href="/forgot-password"' in login.text
    page = TestClient(create_app()).get("/forgot-password")
    assert page.status_code == 200
    assert 'action="/forgot-password"' in page.text


def test_a_request_sends_a_link_back_to_the_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.example.com/")
    auth = supabase_with(monkeypatch)
    response = request_reset()

    assert response.status_code == 200
    assert auth.requests == [
        ("ops@example.com", {"redirect_to": "https://app.example.com/auth/callback"})
    ]
    assert "If an account exists for ops@example.com" in response.text


def test_an_unknown_address_gets_the_same_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    supabase_with(monkeypatch, AuthApiError("User not found", 400, "user_not_found"))
    response = request_reset()
    assert response.status_code == 200
    assert "If an account exists for ops@example.com" in response.text


def test_an_outage_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    supabase_with(monkeypatch, ConnectionError("down"))
    response = request_reset()
    assert response.status_code == 502
    assert "Could not send a reset link right now" in response.text
    assert "If an account exists" not in response.text
