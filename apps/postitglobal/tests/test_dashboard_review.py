"""Reviewing drafts in the dashboard: the hotel page lists drafts waiting for review with
their images, and its buttons approve (queueing the publish) or reject them."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import require_operator
from app.database import get_supabase
from app.jobs import tasks
from app.main import create_app
from tests.fakes import FakeDB

HOTEL = {"id": "hotel-1", "name": "Ege Konak", "location": "Bodrum", "slug": "ege-konak",
         "tier": "standard", "channels": ["instagram"], "contact_email": "a@b.invalid"}  # fmt: skip
POOL = {"id": "asset-1", "hotel_id": "hotel-1", "filename": "pool.jpg", "category": "pool",
        "status": "ready"}  # fmt: skip


def _draft(draft_id: str, status: str, **extra: Any) -> dict[str, Any]:
    return {"id": draft_id, "hotel_id": "hotel-1", "channel": "instagram", "status": status,
            "body_tr": f"Merhaba {draft_id}", "asset_ids": ["asset-1"],
            "created_at": f"2026-11-0{len(draft_id)}T06:00:00Z", **extra}  # fmt: skip


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The drafts whose publish task was queued."""
    queued: list[str] = []
    monkeypatch.setattr(tasks.publish_content_task, "delay", queued.append)
    return queued


def _client(db: FakeDB) -> TestClient:
    app = create_app()
    app.dependency_overrides[require_operator] = lambda: {"id": "operator"}
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False)


def _db(*drafts: dict[str, Any]) -> FakeDB:
    return FakeDB(hotels=[HOTEL], assets=[POOL], content_drafts=list(drafts))


def test_the_hotel_page_lists_drafts_to_review_with_their_images() -> None:
    db = _db(_draft("d1", "pending_review"), _draft("d22", "scheduled"), _draft("d3", "rejected"))
    page = _client(db).get("/dashboard/hotels/hotel-1").text

    assert "Merhaba d1" in page and "Images: pool.jpg" in page
    assert "/dashboard/hotels/hotel-1/drafts/d1/approve" in page
    assert "/drafts/d22/approve" not in page  # decided: listed, but no buttons
    assert "Recent decisions" in page and "Scheduled" in page
    assert "Merhaba d3" not in page  # rejected drafts are done with


def test_a_published_draft_shows_among_the_recent_decisions() -> None:
    page = _client(_db(_draft("d1", "published"))).get("/dashboard/hotels/hotel-1").text
    assert "Merhaba d1" in page and "Published" in page


def test_an_instagram_draft_without_images_is_flagged() -> None:
    db = _db(_draft("d1", "pending_review", asset_ids=[]))
    assert "Instagram will refuse it" in _client(db).get("/dashboard/hotels/hotel-1").text


def test_approving_queues_the_publish_and_returns_to_the_page(published: list[str]) -> None:
    db = _db(_draft("d1", "pending_review"))
    response = _client(db).post("/dashboard/hotels/hotel-1/drafts/d1/approve")

    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard/hotels/hotel-1#review"
    assert db.rows["content_drafts"][0]["status"] == "approved"
    assert published == ["d1"]


def test_a_second_approve_changes_nothing(published: list[str]) -> None:
    db = _db(_draft("d1", "scheduled"))
    response = _client(db).post("/dashboard/hotels/hotel-1/drafts/d1/approve")

    assert response.status_code == 303
    assert db.rows["content_drafts"][0]["status"] == "scheduled"
    assert published == []


def test_rejecting_keeps_the_feedback_and_publishes_nothing(published: list[str]) -> None:
    db = _db(_draft("d1", "pending_review"))
    response = _client(db).post(
        "/dashboard/hotels/hotel-1/drafts/d1/reject", data={"feedback": "  Too long  "}
    )

    assert response.status_code == 303
    draft = db.rows["content_drafts"][0]
    assert (draft["status"], draft["operator_feedback"]) == ("rejected", "Too long")
    assert published == []


def test_a_decided_draft_cant_be_rejected_afterwards() -> None:
    db = _db(_draft("d1", "scheduled"))
    _client(db).post("/dashboard/hotels/hotel-1/drafts/d1/reject")
    assert db.rows["content_drafts"][0]["status"] == "scheduled"


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_a_draft_of_another_hotel_is_not_found(action: str, published: list[str]) -> None:
    db = _db(_draft("d1", "pending_review", hotel_id="hotel-2"))
    response = _client(db).post(f"/dashboard/hotels/hotel-1/drafts/d1/{action}")

    assert response.status_code == 404
    assert db.rows["content_drafts"][0]["status"] == "pending_review"
    assert published == []


def test_generate_queues_this_hotels_generation_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued: list[str] = []
    monkeypatch.setattr(tasks.generate_content_task, "delay", queued.append)
    client = _client(_db())

    response = client.post("/dashboard/hotels/hotel-1/generate")

    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard/hotels/hotel-1?generation=queued#review"
    assert queued == ["hotel-1"]
    assert "Generation queued" in client.get(response.headers["location"]).text
    assert "Generation queued" not in client.get("/dashboard/hotels/hotel-1").text


def test_generate_for_an_unknown_hotel_queues_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    queued: list[str] = []
    monkeypatch.setattr(tasks.generate_content_task, "delay", queued.append)
    response = _client(_db()).post("/dashboard/hotels/hotel-9/generate")
    assert response.status_code == 404
    assert queued == []


def test_deleting_a_draft_removes_it_and_its_image_copies() -> None:
    db = _db(_draft("d1", "failed"), _draft("d22", "pending_review"))
    db.storage.files[("published-media", "hotel-1/d1/asset-1.png")] = b"png"
    db.storage.files[("published-media", "hotel-1/d22/asset-1.png")] = b"png"

    response = _client(db).post("/dashboard/hotels/hotel-1/drafts/d1/delete")

    assert response.status_code == 303
    assert [d["id"] for d in db.rows["content_drafts"]] == ["d22"]
    assert list(db.storage.files) == [("published-media", "hotel-1/d22/asset-1.png")]


@pytest.mark.parametrize("status", ["approved", "scheduled"])
def test_a_draft_at_buffer_cant_be_deleted(status: str) -> None:
    db = _db(_draft("d1", status))
    response = _client(db).post("/dashboard/hotels/hotel-1/drafts/d1/delete")
    assert response.status_code == 409
    assert len(db.rows["content_drafts"]) == 1


def test_the_page_offers_delete_only_where_it_works() -> None:
    db = _db(_draft("d1", "pending_review"), _draft("d22", "failed"), _draft("d3", "scheduled"))
    page = _client(db).get("/dashboard/hotels/hotel-1").text
    assert "/drafts/d1/delete" in page and "/drafts/d22/delete" in page
    assert "/drafts/d3/delete" not in page
    assert "/dashboard/hotels/hotel-1/assets/asset-1/delete" in page


def test_deleting_an_asset_removes_the_file_and_the_row() -> None:
    db = _db()
    db.rows["assets"][0]["storage_path"] = "hotel-1/asset-1/pool.jpg"
    db.storage.files[("hotel-assets", "hotel-1/asset-1/pool.jpg")] = b"jpg"

    response = _client(db).post("/dashboard/hotels/hotel-1/assets/asset-1/delete")

    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard/hotels/hotel-1#media"
    assert db.rows["assets"] == []
    assert db.storage.files == {}


def test_another_hotels_asset_is_not_found() -> None:
    db = FakeDB(hotels=[HOTEL], assets=[{**POOL, "hotel_id": "hotel-2"}], content_drafts=[])
    response = _client(db).post("/dashboard/hotels/hotel-1/assets/asset-1/delete")
    assert response.status_code == 404
    assert len(db.rows["assets"]) == 1
