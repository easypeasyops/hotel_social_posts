"""Editing a draft's Turkish text before it is decided, on the dashboard and on the staff's
/hotel/drafts: the text is saved, its translations are made again from it, and a draft that
is no longer waiting for review stays as it was."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.database import get_supabase
from app.jobs import tasks
from app.main import create_app
from tests.fakes import FakeDB

OPERATOR = SimpleNamespace(id="op-1", app_metadata={"role": "operator"})
STAFF = SimpleNamespace(id="staff-1", app_metadata={})
HOTEL = {"id": "hotel-1", "name": "Ege Konak", "slug": "ege-konak", "channels": ["instagram"]}
NEW_TEXT = "Yeni metin.\n\n#bodrum"


def _db(status: str = "pending_review", hotel_id: str = "hotel-1") -> FakeDB:
    draft = {"id": "d1", "hotel_id": hotel_id, "channel": "instagram", "status": status,
             "body_tr": "Eski metin", "asset_ids": []}  # fmt: skip
    return FakeDB(hotels=[HOTEL], assets=[], content_drafts=[draft],
                  hotel_members=[{"user_id": "staff-1", "hotel_id": "hotel-1",
                                  "role": "hotel_admin"}])  # fmt: skip


@pytest.fixture
def translated(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The drafts whose translation task was queued."""
    queued: list[str] = []
    monkeypatch.setattr(tasks.translate_content_task, "delay", queued.append)
    return queued


def _client(db: FakeDB, user: Any) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False)


# (who, the edit URL, where saving returns to)
PAGES = [
    (OPERATOR, "/dashboard/hotels/hotel-1/drafts/d1/edit", "/dashboard/hotels/hotel-1#draft-d1"),
    (STAFF, "/hotel/drafts/d1/edit", "/hotel/drafts?done=edited#draft-d1"),
]


@pytest.mark.parametrize(("user", "url", "back"), PAGES)
def test_saving_keeps_the_new_text_and_translates_it_again(
    user: Any, url: str, back: str, translated: list[str]
) -> None:
    db = _db()
    response = _client(db, user).post(url, data={"body_tr": f"  {NEW_TEXT}\r\n"})

    assert (response.status_code, response.headers["location"]) == (303, back)
    assert db.rows["content_drafts"][0]["body_tr"] == NEW_TEXT  # trimmed, newlines kept
    assert db.rows["content_drafts"][0]["status"] == "pending_review"
    assert translated == ["d1"]


@pytest.mark.parametrize(("user", "url", "back"), PAGES)
def test_empty_text_is_refused(user: Any, url: str, back: str, translated: list[str]) -> None:
    db = _db()
    response = _client(db, user).post(url, data={"body_tr": "   "})
    assert response.status_code == 422
    assert db.rows["content_drafts"][0]["body_tr"] == "Eski metin" and translated == []


@pytest.mark.parametrize("status", ["approved", "scheduled", "rejected"])
@pytest.mark.parametrize(("user", "url", "back"), PAGES)
def test_a_decided_draft_is_not_changed(
    user: Any, url: str, back: str, status: str, translated: list[str]
) -> None:
    db = _db(status)
    response = _client(db, user).post(url, data={"body_tr": NEW_TEXT})
    assert response.status_code == 303  # back to the page, as a second approve click is
    assert db.rows["content_drafts"][0]["body_tr"] == "Eski metin" and translated == []


def test_staff_cant_edit_another_hotels_draft(translated: list[str]) -> None:
    db = _db(hotel_id="hotel-2")
    response = _client(db, STAFF).post("/hotel/drafts/d1/edit", data={"body_tr": NEW_TEXT})
    assert response.status_code == 404
    assert db.rows["content_drafts"][0]["body_tr"] == "Eski metin" and translated == []


@pytest.mark.parametrize(
    ("user", "page", "url"),
    [
        (OPERATOR, "/dashboard/hotels/hotel-1", "/dashboard/hotels/hotel-1/drafts/d1/edit"),
        (STAFF, "/hotel/drafts", "/hotel/drafts/d1/edit"),
    ],
)
def test_each_pending_draft_offers_its_text_to_edit(user: Any, page: str, url: str) -> None:
    html = _client(_db(), user).get(page).text
    assert f'action="{url}"' in html
    assert '<textarea id="body-d1" name="body_tr"' in html and ">Eski metin</textarea>" in html
