"""The app starts from its environment alone and answers its health check (what the
cluster's probes rely on)."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app

SIGN_IN_PAGES = ["/login", "/forgot-password", "/auth/callback", "/reset-password"]


def test_health() -> None:
    response = TestClient(create_app()).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_the_bare_host_shows_a_signed_out_visitor_the_home_page() -> None:
    root = TestClient(create_app(), follow_redirects=False).get("/")
    assert root.status_code == 200
    assert 'href="/login"' in root.text


def test_api_docs_are_hidden_unless_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    assert TestClient(create_app()).get("/docs").status_code == 404
    monkeypatch.setenv("DEBUG", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    assert TestClient(create_app()).get("/docs").status_code == 200


@pytest.mark.parametrize("missing", ["SECRET_KEY", "SUPABASE_URL", "ANTHROPIC_API_KEY"])
def test_a_missing_secret_stops_start_up(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    monkeypatch.delenv(missing)
    with pytest.raises(ValidationError, match=missing.lower()):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_the_session_cookie_is_secure_by_default() -> None:
    assert Settings(_env_file=None).session_cookie_secure is True  # type: ignore[call-arg]


@pytest.mark.parametrize("path", SIGN_IN_PAGES)
def test_the_sign_in_pages_render(path: str) -> None:
    # Pages that need no session or database: a template change (or a Starlette that
    # renders templates differently) shows here first.
    response = TestClient(create_app()).get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "</html>" in response.text


@pytest.mark.parametrize("path", SIGN_IN_PAGES)
def test_the_sign_in_pages_load_no_third_party_script(path: str) -> None:
    # They handle passwords and tokens (the callback's are in its URL): a script from a CDN
    # would run with access to them. Styles are inline, the font is a stylesheet.
    response = TestClient(create_app()).get(path)
    assert "<script src" not in response.text
