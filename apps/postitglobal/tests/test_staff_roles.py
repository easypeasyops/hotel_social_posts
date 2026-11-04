"""Staff roles on /hotel: hotel admins and content moderators change and decide their hotel's
content; content creators upload and see it, and every content-changing route refuses them."""

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
CHANGES = [
    ("/hotel/files/free/edit", {"name": "havuz", "category": "pool"}),
    ("/hotel/files/free/delete", {}),
    ("/hotel/drafts/d1/approve", {}),
    ("/hotel/drafts/d1/edit", {"body_tr": "Yeni metin"}),
    ("/hotel/drafts/d1/images", {}),
    ("/hotel/drafts/d1/reject", {}),
    ("/hotel/drafts/d1/delete", {}),
]
BUTTONS = ["/hotel/files/free/edit", "/hotel/drafts/d1/approve", "/hotel/drafts/d1/delete"]


def _client(role: str) -> tuple[TestClient, FakeDB]:
    db = FakeDB(
        hotels=[{"id": "hotel-1", "name": "Ege Konak", "slug": "ege-konak"}],
        hotel_members=[{"user_id": "staff-1", "hotel_id": "hotel-1", "role": role}],
        assets=[{"id": "free", "hotel_id": "hotel-1", "filename": "free.jpg",
                 "category": "pool", "status": "ready", "storage_path": "hotel-1/free.jpg"}],
        content_drafts=[{"id": "d1", "hotel_id": "hotel-1", "channel": "instagram",
                         "status": "pending_review", "body_tr": "Merhaba", "asset_ids": []}],
    )  # fmt: skip
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: STAFF
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False), db


@pytest.fixture(autouse=True)
def no_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks.publish_content_task, "delay", lambda *_: None)
    monkeypatch.setattr(tasks.translate_content_task, "delay", lambda *_: None)


@pytest.mark.parametrize("role", ["hotel_admin", "content_moderator"])
@pytest.mark.parametrize(("path", "form"), CHANGES)
def test_admins_and_moderators_change_content(role: str, path: str, form: dict[str, Any]) -> None:
    client, _ = _client(role)
    assert client.post(path, data=form).status_code == 303


@pytest.mark.parametrize(("path", "form"), CHANGES)
def test_a_content_creator_cannot_change_content(path: str, form: dict[str, Any]) -> None:
    client, db = _client("content_creator")
    response = client.post(path, data=form)

    assert response.status_code == 403
    assert db.writes == []


@pytest.mark.parametrize("role", ["hotel_admin", "content_moderator"])
def test_admins_and_moderators_see_the_buttons(role: str) -> None:
    client, _ = _client(role)
    pages = client.get("/hotel").text + client.get("/hotel/drafts").text
    assert all(action in pages for action in BUTTONS)


def test_a_content_creator_uploads_and_sees_without_buttons() -> None:
    client, _ = _client("content_creator")
    home, drafts = client.get("/hotel"), client.get("/hotel/drafts")

    assert home.status_code == drafts.status_code == 200
    assert 'href="/hotel/upload"' in home.text
    assert "Merhaba" in drafts.text  # the draft and its preview, to look at
    assert not any(action in home.text + drafts.text for action in BUTTONS)
    assert client.get("/hotel/upload").status_code == 303
