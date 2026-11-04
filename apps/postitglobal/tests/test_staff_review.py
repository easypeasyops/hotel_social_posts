"""Hotel staff review their own hotel's drafts at /hotel/drafts: approving queues the publish
as on the dashboard, rejecting keeps the feedback; another hotel's draft is out of reach."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.database import get_supabase
from app.jobs import tasks
from app.main import create_app
from tests.fakes import FakeDB

STAFF = SimpleNamespace(id="staff-1", app_metadata={})
SIGNED = "https://supabase.invalid/storage/v1/object/sign/hotel-assets"
HOTEL = {"id": "hotel-1", "name": "Ege Konak", "slug": "ege-konak"}
POOL = {"id": "asset-1", "hotel_id": "hotel-1", "filename": "pool.jpg", "category": "pool",
        "status": "ready", "storage_path": "hotel-1/asset-1/pool.jpg"}  # fmt: skip


def _draft(draft_id: str, status: str, hotel_id: str = "hotel-1") -> dict[str, Any]:
    return {"id": draft_id, "hotel_id": hotel_id, "channel": "instagram", "status": status,
            "body_tr": f"Merhaba {draft_id}", "asset_ids": ["asset-1"]}  # fmt: skip


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The drafts whose publish task was queued."""
    queued: list[str] = []
    monkeypatch.setattr(tasks.publish_content_task, "delay", queued.append)
    return queued


def _db(*drafts: dict[str, Any]) -> FakeDB:
    return FakeDB(
        hotels=[HOTEL],
        assets=[POOL],
        content_drafts=list(drafts),
        hotel_members=[{"user_id": "staff-1", "hotel_id": "hotel-1"}],
    )


def _staff(db: FakeDB) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: STAFF
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False)


def test_the_page_lists_their_hotels_pending_drafts_only() -> None:
    db = _db(_draft("d1", "pending_review"), _draft("d2", "approved"),
             _draft("d3", "pending_review", hotel_id="hotel-2"))  # fmt: skip
    page = _staff(db).get("/hotel/drafts")

    assert page.status_code == 200
    assert "Merhaba d1" in page.text
    assert "Merhaba d2" not in page.text and "Merhaba d3" not in page.text
    assert 'data-preview="instagram"' in page.text  # the post as it will look, with its image
    assert f'src="{SIGNED}/hotel-1/asset-1/pool.jpg?token=t"' in page.text
    assert "1 paylaşım kararınızı bekliyor" in _staff(db).get("/hotel").text


def test_approve_queues_the_publish(published: list[str]) -> None:
    db = _db(_draft("d1", "pending_review"))
    response = _staff(db).post("/hotel/drafts/d1/approve")

    assert response.headers["location"] == "/hotel/drafts?done=approved"
    assert db.rows["content_drafts"][0]["status"] == "approved"
    assert published == ["d1"]


def test_reject_keeps_the_feedback(published: list[str]) -> None:
    db = _db(_draft("d1", "pending_review"))
    _staff(db).post("/hotel/drafts/d1/reject", data={"feedback": "  Fotoğraf eski  "})

    draft = db.rows["content_drafts"][0]
    assert (draft["status"], draft["operator_feedback"]) == ("rejected", "Fotoğraf eski")
    assert published == []


def test_delete_removes_a_pending_draft() -> None:
    db = _db(_draft("d1", "pending_review"), _draft("d2", "pending_review"))
    client = _staff(db)
    assert "/hotel/drafts/d1/delete" in client.get("/hotel/drafts").text

    response = client.post("/hotel/drafts/d1/delete")

    assert (response.status_code, response.headers["location"]) == (
        303,
        "/hotel/drafts?done=deleted",
    )
    assert [d["id"] for d in db.rows["content_drafts"]] == ["d2"]


@pytest.mark.parametrize("status", ["approved", "scheduled", "published"])
def test_a_draft_at_buffer_cant_be_deleted(status: str) -> None:
    db = _db(_draft("d1", status))
    assert _staff(db).post("/hotel/drafts/d1/delete").status_code == 409
    assert len(db.rows["content_drafts"]) == 1


@pytest.mark.parametrize("action", ["approve", "reject", "delete"])
def test_another_hotels_draft_is_out_of_reach(action: str, published: list[str]) -> None:
    db = _db(_draft("d3", "pending_review", hotel_id="hotel-2"))
    assert _staff(db).post(f"/hotel/drafts/d3/{action}").status_code == 404
    assert db.rows["content_drafts"][0]["status"] == "pending_review"
    assert published == []


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_a_decided_draft_stays_as_it_is(action: str, published: list[str]) -> None:
    db = _db(_draft("d1", "scheduled"))
    assert _staff(db).post(f"/hotel/drafts/d1/{action}").status_code == 303
    assert db.rows["content_drafts"][0]["status"] == "scheduled"
    assert published == []
