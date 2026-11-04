"""The home page at /: hotels that don't use postitglobal yet see it; a browser already signed
in goes on to its own pages, as a new session would (operators to the dashboard, staff to
/hotel)."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import dependencies
from app.auth.sessions import SESSION_COOKIE
from app.main import create_app
from tests.fakes import FakeDB

OPERATOR = SimpleNamespace(id="op-1", app_metadata={"role": "operator"})
STAFF = SimpleNamespace(id="staff-1", app_metadata={})
NOBODY = SimpleNamespace(id="user-9", app_metadata={})


def visit(monkeypatch: pytest.MonkeyPatch, user: object | None) -> Any:
    """GET / from a browser with a session cookie; `user` is who it belongs to (None: expired)."""

    def current_user(request: object, credentials: object) -> object:
        if user is None:
            raise HTTPException(status_code=401, detail="Session expired")
        return user

    members = [{"user_id": "staff-1", "hotel_id": "hotel-1", "email": "s@example.com"}]
    monkeypatch.setattr(dependencies, "get_current_user", current_user)
    monkeypatch.setattr(dependencies, "get_supabase", lambda: FakeDB(hotel_members=members))
    client = TestClient(create_app(), follow_redirects=False)
    client.cookies.set(SESSION_COOKIE, "session-id")
    return client.get("/")


def test_a_visitor_sees_the_home_page() -> None:
    response = TestClient(create_app(), follow_redirects=False).get("/")
    assert response.status_code == 200
    page = response.text
    assert "Fotoğrafları siz yükleyin, gönderileri yapay zekâ yazsın." in page
    assert 'src="/static/logo.png"' in page
    assert '<a class="btn btn-primary" href="/login">Giriş yap</a>' in page
    assert "<script" not in page


@pytest.mark.parametrize(
    ("user", "destination"), [(OPERATOR, "/dashboard/hotels"), (STAFF, "/hotel")]
)
def test_a_signed_in_browser_goes_on_to_its_pages(
    monkeypatch: pytest.MonkeyPatch, user: object, destination: str
) -> None:
    response = visit(monkeypatch, user)
    assert (response.status_code, response.headers["location"]) == (303, destination)


@pytest.mark.parametrize("user", [NOBODY, None], ids=["no access", "expired session"])
def test_a_session_without_a_destination_sees_the_home_page(
    monkeypatch: pytest.MonkeyPatch, user: object | None
) -> None:
    response = visit(monkeypatch, user)
    assert response.status_code == 200
