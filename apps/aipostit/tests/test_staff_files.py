"""Staff rename, recategorize and delete their hotel's files on /hotel, except the ones a
draft has taken to Buffer (approved, scheduled or published)."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.database import get_supabase
from app.main import create_app
from tests.fakes import NAMED, FakeDB

STAFF = SimpleNamespace(user_metadata=NAMED, id="staff-1", app_metadata={"provider": "email"})


def _asset(asset_id: str, hotel_id: str = "hotel-1") -> dict[str, Any]:
    return {"id": asset_id, "hotel_id": hotel_id, "filename": f"{asset_id}.jpg",
            "category": "pool", "status": "ready",
            "storage_path": f"{hotel_id}/{asset_id}.jpg"}  # fmt: skip


def _db(*drafts: dict[str, Any]) -> FakeDB:
    db = FakeDB(
        hotels=[{"id": "hotel-1", "name": "Lagoon Bay", "slug": "lagoon-bay"}],
        hotel_members=[
            {
                "user_id": "staff-1",
                "hotel_id": "hotel-1",
                "email": "s@example.com",
                "role": "hotel_admin",
            }
        ],  # fmt: skip
        assets=[_asset("free"), _asset("sent"), _asset("theirs", hotel_id="hotel-2")],
        content_drafts=[
            {"id": "d1", "hotel_id": "hotel-1", "status": "scheduled", "asset_ids": ["sent"]},
            {"id": "d2", "hotel_id": "hotel-1", "status": "pending_review", "asset_ids": ["free"]},
            *drafts,
        ],
    )
    db.storage.files[("hotel-assets", "hotel-1/free.jpg")] = b"jpg"
    return db


def _client(db: FakeDB) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: STAFF
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False)


def _asset_row(db: FakeDB, asset_id: str) -> dict[str, Any]:
    return next(a for a in db.rows["assets"] if a["id"] == asset_id)


def test_the_page_offers_edit_and_delete_only_for_files_not_sent() -> None:
    page = _client(_db()).get("/hotel").text
    assert "/hotel/files/free/edit" in page and "/hotel/files/free/delete" in page
    assert "/hotel/files/sent/" not in page
    assert "gönderilen bir paylaşımda" in page


def test_renaming_keeps_the_extension_and_changes_the_category() -> None:
    db = _db()
    response = _client(db).post(
        "/hotel/files/free/edit", data={"name": "  Gün batımı.JPG ", "category": "beach"}
    )

    assert (response.status_code, response.headers["location"]) == (303, "/hotel#file-free")
    row = _asset_row(db, "free")
    assert (row["filename"], row["category"]) == ("Gün batımı.jpg", "beach")
    assert row["storage_path"] == "hotel-1/free.jpg"  # the stored object stays where it is


@pytest.mark.parametrize("name", ["   ", ".jpg", "a/b"])
def test_an_empty_or_path_like_name_is_refused(name: str) -> None:
    db = _db()
    response = _client(db).post("/hotel/files/free/edit", data={"name": name, "category": "pool"})
    assert response.status_code == 422
    assert _asset_row(db, "free")["filename"] == "free.jpg"


def test_an_unknown_category_is_refused() -> None:
    response = _client(_db()).post("/hotel/files/free/edit", data={"name": "x", "category": "spa"})
    assert response.status_code == 422


def test_deleting_removes_the_file_and_its_record() -> None:
    db = _db()
    response = _client(db).post("/hotel/files/free/delete")

    assert (response.status_code, response.headers["location"]) == (303, "/hotel#files")
    assert [a["id"] for a in db.rows["assets"]] == ["sent", "theirs"]
    assert db.storage.files == {}


@pytest.mark.parametrize("status", ["approved", "scheduled", "published"])
@pytest.mark.parametrize("action", ["edit", "delete"])
def test_a_file_a_draft_took_to_buffer_stays_as_it_is(status: str, action: str) -> None:
    db = _db({"id": "d3", "hotel_id": "hotel-1", "status": status, "asset_ids": ["free"]})
    response = _client(db).post(
        f"/hotel/files/free/{action}", data={"name": "new", "category": "room"}
    )

    assert response.status_code == 409
    assert _asset_row(db, "free") == _asset("free")


@pytest.mark.parametrize("action", ["edit", "delete"])
def test_another_hotels_file_is_not_found(action: str) -> None:
    db = _db()
    response = _client(db).post(
        f"/hotel/files/theirs/{action}", data={"name": "new", "category": "room"}
    )
    assert response.status_code == 404
    assert _asset_row(db, "theirs") == _asset("theirs", hotel_id="hotel-2")
