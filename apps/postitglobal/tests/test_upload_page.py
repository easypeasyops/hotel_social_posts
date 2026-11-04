import re

import pytest
from fastapi.testclient import TestClient

from app.assets.models import AssetCategory
from app.main import create_app
from tests.fakes import FakeDB

HOTEL = {"id": "h1", "name": "Lykia Resort", "slug": "lykia-resort"}


@pytest.fixture
def page(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr("app.database.get_supabase", lambda: FakeDB(hotels=[HOTEL]))
    response = TestClient(create_app()).get("/upload/lykia-resort")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    return response.text


def test_the_page_offers_every_category_the_api_accepts(page: str) -> None:
    offered = re.findall(r'name="category" value="([a-z]+)"', page)
    assert offered == [c.value for c in AssetCategory]


def test_the_page_greets_the_hotel_and_hides_the_expired_link_notice(page: str) -> None:
    assert "Lykia Resort" in page
    assert '<div id="access-error" role="alert" class="hidden' in page


def test_the_page_shows_the_logo_and_the_logo_is_served(page: str) -> None:
    assert '<img src="/static/logo.png" alt="postitglobal"' in page
    response = TestClient(create_app()).get("/static/logo.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
