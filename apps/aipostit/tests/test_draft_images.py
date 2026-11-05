"""Choosing a pending draft's images on the review pages: which of the hotel's ready photos
the post carries, in what order. Only photos a post can carry are offered, at most ten."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.database import get_supabase
from app.main import create_app
from app.publishing.buffer import MAX_IMAGES
from tests.fakes import FakeDB

OPERATOR = SimpleNamespace(id="op-1", app_metadata={"role": "operator"})
STAFF = SimpleNamespace(id="staff-1", app_metadata={})
HOTEL = {"id": "hotel-1", "name": "Ege Konak", "slug": "ege-konak", "channels": ["instagram"]}


def _asset(asset_id: str, filename: str, status: str = "ready", hotel_id: str = "hotel-1") -> dict:
    return {"id": asset_id, "hotel_id": hotel_id, "filename": filename, "status": status,
            "category": "pool", "storage_path": f"{hotel_id}/{asset_id}/{filename}"}  # fmt: skip


ASSETS = [
    _asset("pool", "pool.jpg"),
    _asset("room", "room.png"),
    _asset("food", "food.jpg"),
    _asset("drone", "drone.mp4"),  # a video: posts carry images only
    _asset("lobby", "lobby.jpg", status="pending"),  # not uploaded yet
    _asset("theirs", "theirs.jpg", hotel_id="hotel-2"),  # another hotel's
]


def _db(status: str = "pending_review", assets: list[dict] = ASSETS) -> FakeDB:
    draft = {"id": "d1", "hotel_id": "hotel-1", "channel": "instagram", "status": status,
             "body_tr": "Metin", "asset_ids": ["pool"]}  # fmt: skip
    return FakeDB(hotels=[HOTEL], assets=list(assets), content_drafts=[draft],
                  hotel_members=[{"user_id": "staff-1", "hotel_id": "hotel-1",
                                  "role": "hotel_admin"}])  # fmt: skip


def _client(db: FakeDB, user: Any) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False)


def _choice(chosen: dict[str, str], offered: list[str]) -> dict[str, list[str]]:
    """The form as the browser sends it: every offered photo with its order box (blank when
    not given), and the ticked ones."""
    return {"choice": offered, "order": [chosen.get(i, "") for i in offered],
            "asset_ids": list(chosen)}  # fmt: skip


OFFERED = ["pool", "room", "food"]
PAGES = [
    (OPERATOR, "/dashboard/hotels/hotel-1/drafts/d1/images", "/dashboard/hotels/hotel-1#draft-d1"),
    (STAFF, "/hotel/drafts/d1/images", "/hotel/drafts?done=images#draft-d1"),
]


@pytest.mark.parametrize(("user", "url", "back"), PAGES)
def test_the_ticked_photos_are_saved_in_the_order_given(user: Any, url: str, back: str) -> None:
    db = _db()
    # room 1st, food 2nd; pool ticked without a number goes after the numbered ones.
    form = _choice({"pool": "", "food": "2", "room": "1"}, OFFERED)
    response = _client(db, user).post(url, data=form)

    assert (response.status_code, response.headers["location"]) == (303, back)
    assert db.rows["content_drafts"][0]["asset_ids"] == ["room", "food", "pool"]


@pytest.mark.parametrize(("user", "url", "back"), PAGES)
def test_untick_all_leaves_a_text_only_post(user: Any, url: str, back: str) -> None:
    db = _db()
    _client(db, user).post(url, data=_choice({}, OFFERED))
    assert db.rows["content_drafts"][0]["asset_ids"] == []


@pytest.mark.parametrize("asset_id", ["drone", "lobby", "theirs", "nope"])
def test_only_the_hotels_ready_photos_can_be_chosen(asset_id: str) -> None:
    db = _db()
    response = _client(db, OPERATOR).post(
        "/dashboard/hotels/hotel-1/drafts/d1/images", data=_choice({asset_id: "1"}, [asset_id])
    )
    assert response.status_code == 422
    assert db.rows["content_drafts"][0]["asset_ids"] == ["pool"]


def test_at_most_ten_photos() -> None:
    many = [_asset(f"img{n}", f"{n}.jpg") for n in range(MAX_IMAGES + 1)]
    db = _db(assets=many)
    chosen = {a["id"]: "" for a in many}
    response = _client(db, OPERATOR).post(
        "/dashboard/hotels/hotel-1/drafts/d1/images", data=_choice(chosen, list(chosen))
    )
    assert response.status_code == 422


@pytest.mark.parametrize(("user", "url", "back"), PAGES)
def test_a_decided_draft_keeps_its_photos(user: Any, url: str, back: str) -> None:
    db = _db("approved")
    assert _client(db, user).post(url, data=_choice({"room": "1"}, OFFERED)).status_code == 303
    assert db.rows["content_drafts"][0]["asset_ids"] == ["pool"]


@pytest.mark.parametrize(
    ("user", "page", "url"),
    [
        (OPERATOR, "/dashboard/hotels/hotel-1", "/dashboard/hotels/hotel-1/drafts/d1/images"),
        (STAFF, "/hotel/drafts", "/hotel/drafts/d1/images"),
    ],
)
def test_the_picker_offers_the_hotels_postable_photos_with_thumbnails(
    user: Any, page: str, url: str
) -> None:
    db = _db()
    html = _client(db, user).get(page).text

    assert f'action="{url}"' in html
    offered = [i for i in ["pool", "room", "food", "drone", "lobby"] if f'value="{i}"' in html]
    assert offered == ["pool", "room", "food"]
    assert 'name="asset_ids" value="pool" checked' in html  # the draft's current photo
    assert 'name="order" value="1"' in html  # ... first
    signed = "https://supabase.invalid/storage/v1/object/sign/hotel-assets/hotel-1/room/room.png"
    assert f'src="{signed}?token=t"' in html
    assert len(db.storage.signed) == 1  # previews and thumbnails in one Storage request
