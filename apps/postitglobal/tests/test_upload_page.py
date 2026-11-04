import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from app.assets.models import AssetCategory
from app.auth import dependencies
from app.auth.dependencies import signed_in_staff_hotel
from app.auth.sessions import SESSION_COOKIE
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


def test_each_chosen_file_gets_its_own_category(page: str) -> None:
    # Rows are cloned from this template; the radio group above only sets their default.
    row = page[page.index('<template id="file-row">') : page.index("</template>")]
    assert re.findall(r'<option value="([a-z]+)"', row) == [c.value for c in AssetCategory]
    assert 'name="file-category"' in row
    assert "Kaldır" in row


def _page_for(monkeypatch: pytest.MonkeyPatch, staff_hotel: str | None) -> str:
    monkeypatch.setattr("app.database.get_supabase", lambda: FakeDB(hotels=[HOTEL]))
    app = create_app()
    app.dependency_overrides[signed_in_staff_hotel] = lambda: staff_hotel
    return TestClient(app).get("/upload/lykia-resort").text


def test_the_hotels_signed_in_staff_get_a_way_back(monkeypatch: pytest.MonkeyPatch) -> None:
    assert '<a href="/hotel"' in _page_for(monkeypatch, "h1")


@pytest.mark.parametrize("staff_hotel", [None, "another-hotel"])
def test_anyone_else_with_the_link_gets_no_back_link(
    monkeypatch: pytest.MonkeyPatch, staff_hotel: str | None
) -> None:
    # None: no session, an expired one, or an account that isn't staff (an operator, say).
    assert '<a href="/hotel"' not in _page_for(monkeypatch, staff_hotel)


STAFF = SimpleNamespace(id="staff-1")


def _request(cookie: str | None) -> Request:
    headers = [(b"cookie", f"{SESSION_COOKIE}={cookie}".encode())] if cookie else []
    return Request({"type": "http", "headers": headers})


def _signed_in(monkeypatch: pytest.MonkeyPatch, user: object) -> None:
    def current_user(*_: object) -> object:
        if user is None:
            raise HTTPException(status_code=401)
        return user

    monkeypatch.setattr(dependencies, "get_current_user", current_user)
    db = FakeDB(hotel_members=[{"user_id": "staff-1", "hotel_id": "h1"}])
    monkeypatch.setattr(dependencies, "get_supabase", lambda: db)


def test_a_staff_session_names_its_hotel(monkeypatch: pytest.MonkeyPatch) -> None:
    _signed_in(monkeypatch, STAFF)
    assert signed_in_staff_hotel(_request("session-1")) == "h1"


@pytest.mark.parametrize(
    ("cookie", "user"),
    [(None, STAFF), ("expired", None), ("session-2", SimpleNamespace(id="operator-1"))],
)
def test_no_session_a_dead_one_or_a_non_member_names_none(
    monkeypatch: pytest.MonkeyPatch, cookie: str | None, user: object
) -> None:
    _signed_in(monkeypatch, user)
    assert signed_in_staff_hotel(_request(cookie)) is None
