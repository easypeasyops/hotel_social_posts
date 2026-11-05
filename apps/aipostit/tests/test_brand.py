import pytest
from fastapi.testclient import TestClient

from app.main import create_app, templates
from tests.fakes import FakeDB

LOGO = 'src="/static/logo.png"'
ICON = '<link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32.png" />'


@pytest.mark.parametrize("name", ["logo.png", "favicon-32.png", "apple-touch-icon.png"])
def test_the_brand_images_are_served(name: str) -> None:
    response = TestClient(create_app()).get(f"/static/{name}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


@pytest.mark.parametrize(
    "path", ["/login", "/forgot-password", "/signup", "/auth/callback", "/reset-password"]
)
def test_the_sign_in_pages_show_the_logo_and_the_tab_icon(path: str) -> None:
    page = TestClient(create_app()).get(path).text
    assert LOGO in page
    assert ICON in page


def test_the_upload_page_shows_the_logo_and_the_tab_icon(monkeypatch: pytest.MonkeyPatch) -> None:
    hotel = {"id": "h1", "name": "Lykia Resort", "slug": "lykia-resort"}
    monkeypatch.setattr("app.database.get_supabase", lambda: FakeDB(hotels=[hotel]))
    page = TestClient(create_app()).get("/upload/lykia-resort").text
    assert LOGO in page
    assert ICON in page


def test_the_dashboard_nav_shows_the_logo_and_the_tab_icon() -> None:
    page = templates.get_template("base.html").render(messages=None)
    assert f'<a href="/dashboard/hotels"><img {LOGO}' in page
    assert ICON in page


def test_the_customer_pages_use_the_logos_purple(monkeypatch: pytest.MonkeyPatch) -> None:
    # The sign-in layout, the upload page and the staff layout each carry the customer
    # palette inline (no shared stylesheet yet): all three must name the logo's purple.
    hotel = {"id": "h1", "name": "Lykia Resort", "slug": "lykia-resort"}
    monkeypatch.setattr("app.database.get_supabase", lambda: FakeDB(hotels=[hotel]))
    client = TestClient(create_app())
    for path in ["/login", "/upload/lykia-resort"]:
        assert "#3b05c1" in client.get(path).text, path
    staff = templates.get_template("staff/base.html").render(hotel={"name": "Lykia Resort"})
    assert "#3b05c1" in staff


def test_the_hotel_staff_pages_show_the_tab_icon() -> None:
    page = templates.get_template("staff/base.html").render(hotel={"name": "Lykia Resort"})
    assert ICON in page
