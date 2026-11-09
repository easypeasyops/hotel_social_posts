"""The operator, or the hotel's admin, revokes a pending invite: it shows as revoked, its link
leaves the table and fails at /signup. Another hotel's invite, or an accepted one, is left
alone; moderators and creators can't revoke."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user, require_operator
from app.auth.upload_tokens import create_recorded_invite_token
from app.database import get_supabase
from app.main import create_app
from tests.fakes import FakeDB
from tests.test_invite_table import HOTEL, invite, links
from tests.test_recorded_invite_signup import supabase_with
from tests.test_staff_signup import sign_up


def db_with(*rows: dict[str, Any]) -> FakeDB:
    return FakeDB(hotels=[HOTEL], staff_invites=list(rows))


def operator(db: FakeDB) -> TestClient:
    app = create_app()
    app.dependency_overrides[require_operator] = lambda: SimpleNamespace(email="op@example.com")
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False)


def staff(db: FakeDB, role: str = "hotel_admin", hotel_id: str = "hotel-1") -> TestClient:
    db.rows["hotel_members"] = [
        {"user_id": "me", "hotel_id": hotel_id, "email": "admin@example.com", "role": role}
    ]
    app = create_app()
    me = SimpleNamespace(id="me", email="admin@example.com", app_metadata={})
    app.dependency_overrides[get_current_user] = lambda: me
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False)


def row(db: FakeDB) -> dict[str, Any]:
    return db.rows["staff_invites"][0]


def test_the_operator_revokes_a_pending_invite() -> None:
    db = db_with(invite("new@example.com"))
    client = operator(db)
    assert "id-new" in links(client.get("/dashboard/hotels/hotel-1").text)

    response = client.post("/dashboard/hotels/hotel-1/invites/id-new/revoke")
    assert (response.status_code, response.headers["location"]) == (
        303,
        "/dashboard/hotels/hotel-1?done=revoked#invites",
    )
    assert (row(db)["revoked_at"] is not None, row(db)["revoked_by_email"]) == (
        True,
        "op@example.com",
    )
    page = client.get("/dashboard/hotels/hotel-1").text
    assert "revoked" in page and links(page) == {}


def test_the_hotel_admin_revokes_the_operators_invite() -> None:
    db = db_with(invite("new@example.com", invited_by_email="op@example.com"))
    client = staff(db)

    response = client.post("/hotel/staff/invites/id-new/revoke")
    assert (response.status_code, response.headers["location"]) == (
        303,
        "/hotel/staff?done=revoked#invites",
    )
    assert row(db)["revoked_by_email"] == "admin@example.com"
    page = client.get("/hotel/staff?done=revoked").text
    assert "iptal edildi" in page and "Kaydedildi." in page and links(page) == {}


@pytest.mark.parametrize("role", ["content_moderator", "content_creator"])
def test_other_staff_roles_cant_revoke(role: str) -> None:
    db = db_with(invite("new@example.com"))
    assert staff(db, role).post("/hotel/staff/invites/id-new/revoke").status_code == 403
    assert row(db)["revoked_at"] is None


def test_another_hotels_invite_is_left_alone() -> None:
    db = db_with(invite("new@example.com", hotel_id="hotel-2"))
    staff(db).post("/hotel/staff/invites/id-new/revoke")  # this admin's hotel is hotel-1
    operator(db).post("/dashboard/hotels/hotel-1/invites/id-new/revoke")  # wrong hotel in URL
    assert row(db)["revoked_at"] is None


def test_an_ended_invite_is_left_alone() -> None:
    accepted = "2026-11-08T11:00:00+00:00"
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    db = db_with(invite("joined@example.com", accepted_at=accepted))
    db.rows["staff_invites"].append(invite("lapsed@example.com", expires_at=past))
    client = operator(db)
    client.post("/dashboard/hotels/hotel-1/invites/id-joined/revoke")
    client.post("/dashboard/hotels/hotel-1/invites/id-lapsed/revoke")

    assert [r["revoked_at"] for r in db.rows["staff_invites"]] == [None, None]
    assert row(db)["accepted_at"] == accepted


def test_a_revoked_invites_link_fails_at_sign_up(monkeypatch: pytest.MonkeyPatch) -> None:
    expires = datetime.now(UTC) + timedelta(days=5)
    db, admin = supabase_with(
        monkeypatch, invite("new@example.com", expires_at=expires.isoformat())
    )
    link = create_recorded_invite_token("hotel-1", "id-new", "new@example.com", expires)
    operator(db).post("/dashboard/hotels/hotel-1/invites/id-new/revoke")

    response = sign_up(link, email="new@example.com")
    assert response.status_code == 400
    assert "invite link is invalid or has expired" in response.text
    assert admin.created == []
