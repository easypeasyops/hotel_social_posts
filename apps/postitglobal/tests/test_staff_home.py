"""Hotel staff (a row in hotel_members) sign in to /hotel, which shows their own hotel's files
and opens the upload page for it; they don't reach the operator dashboard."""

from collections.abc import Iterator
from types import SimpleNamespace
from urllib.parse import unquote

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.auth import dependencies, router, sessions
from app.auth.dependencies import get_current_user
from app.auth.upload_tokens import verify_upload_token
from app.database import get_supabase
from app.main import create_app
from tests.fakes import FakeDB

STAFF = SimpleNamespace(id="staff-1", app_metadata={"provider": "email"})
HOTELS = [{"id": "hotel-1", "name": "Lagoon Bay", "slug": "lagoon-bay"}, {"id": "hotel-2"}]
ASSETS = [
    {
        "id": "a1",
        "hotel_id": "hotel-1",
        "filename": "pool.jpg",
        "category": "pool",
        "status": "ready",
        "storage_path": "hotel-1/a1/pool.jpg",
    },
    {
        "id": "a3",
        "hotel_id": "hotel-1",
        "filename": "tour.mp4",
        "category": "exterior",
        "status": "ready",
        "storage_path": "hotel-1/a3/tour.mp4",
    },
    {
        "id": "a2",
        "hotel_id": "hotel-2",
        "filename": "other.jpg",
        "category": "room",
        "status": "ready",
    },
]


def database() -> FakeDB:
    return FakeDB(
        hotels=HOTELS,
        assets=ASSETS,
        hotel_members=[{"user_id": "staff-1", "hotel_id": "hotel-1", "email": "s@example.com"}],
    )


def signed_in_as(user: object) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_supabase] = database
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Iterator[fakeredis.FakeRedis]:
    redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(sessions, "get_session_store", lambda: redis)
    yield redis


def test_staff_sign_in_lands_on_their_hotel(
    monkeypatch: pytest.MonkeyPatch, store: fakeredis.FakeRedis
) -> None:
    tokens = SimpleNamespace(**{"access_token": "a", "refresh_token": "r", "expires_at": None})
    auth = SimpleNamespace(
        sign_in_with_password=lambda credentials: SimpleNamespace(user=STAFF, session=tokens)
    )
    monkeypatch.setattr(router, "get_supabase_anon", lambda: SimpleNamespace(auth=auth))
    monkeypatch.setattr(dependencies, "get_supabase", database)

    client = TestClient(create_app(), follow_redirects=False)
    response = client.post("/login", data={"email": "s@example.com", "password": "secret-pass"})

    assert (response.status_code, response.headers["location"]) == (303, "/hotel")
    assert len(store.keys("web-session:*")) == 1


def test_the_home_lists_their_own_hotels_files_only() -> None:
    response = signed_in_as(STAFF).get("/hotel")

    assert response.status_code == 200
    assert "Lagoon Bay" in response.text
    assert "pool.jpg" in response.text
    assert "other.jpg" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_photos_show_as_thumbnails_that_open_the_full_image() -> None:
    page = signed_in_as(STAFF).get("/hotel").text

    signed = (
        "https://supabase.invalid/storage/v1/object/sign/hotel-assets/hotel-1/a1/pool.jpg?token=t"
    )
    assert f'<img src="{signed}"' in page
    assert f'data-view="{signed}"' in page and 'id="viewer"' in page
    # A video has no thumbnail yet, only its type; nothing of it is signed.
    assert "MP4" in page and "hotel-1/a3/tour.mp4" not in page


def test_upload_opens_the_upload_page_with_a_link_for_their_hotel() -> None:
    response = signed_in_as(STAFF).get("/hotel/upload")

    assert response.status_code == 303
    page, token = response.headers["location"].split("#token=")
    assert page == "/upload/lagoon-bay"
    assert verify_upload_token(unquote(token), "hotel-1")


def test_an_account_that_is_not_staff_is_refused() -> None:
    nobody = SimpleNamespace(id="nobody-1", app_metadata={})
    assert signed_in_as(nobody).get("/hotel").status_code == 403


def test_staff_dont_reach_the_operator_dashboard() -> None:
    assert signed_in_as(STAFF).get("/dashboard/hotels").status_code == 403


def test_signed_out_goes_to_sign_in() -> None:
    response = TestClient(create_app(), follow_redirects=False).get("/hotel")
    assert (response.status_code, response.headers["location"]) == (303, "/login")
