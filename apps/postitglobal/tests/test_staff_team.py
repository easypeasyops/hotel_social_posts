"""A hotel admin manages the hotel's staff at /hotel/staff: invite links with a role, role
changes and removal, for the hotel's other members only. Other roles are refused."""

from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.upload_tokens import read_staff_invite
from app.database import get_supabase
from app.main import create_app
from tests.fakes import FakeDB


def _client(role: str = "hotel_admin") -> tuple[TestClient, FakeDB]:
    db = FakeDB(
        hotels=[{"id": "hotel-1", "name": "Ege Konak", "slug": "ege-konak"}],
        hotel_members=[
            {"user_id": "me", "hotel_id": "hotel-1", "email": "me@example.com", "role": role},
            {"user_id": "u2", "hotel_id": "hotel-1", "email": "u2@example.com",
             "role": "content_creator"},
            {"user_id": "u3", "hotel_id": "hotel-2", "email": "u3@example.com",
             "role": "content_creator"},
        ],
    )  # fmt: skip
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="me", app_metadata={})
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False), db


def _roles(db: FakeDB) -> dict[str, str]:
    return {m["user_id"]: m["role"] for m in db.rows["hotel_members"]}


def test_the_admin_sees_the_team_of_their_hotel() -> None:
    client, _ = _client()
    page = client.get("/hotel/staff")

    assert page.status_code == 200
    assert "u2@example.com" in page.text and "u3@example.com" not in page.text
    assert 'action="/hotel/staff/u2/role"' in page.text
    assert 'action="/hotel/staff/me/role"' not in page.text  # not their own
    assert 'href="/hotel/staff"' in client.get("/hotel").text


def test_the_admin_makes_an_invite_for_a_role() -> None:
    client, _ = _client()
    page = client.post("/hotel/staff/invite", data={"role": "content_moderator"})

    invite = page.text.split("/signup#invite=", 1)[1].split('"', 1)[0]
    assert read_staff_invite(unquote(invite)) == ("hotel-1", "content_moderator", None)
    assert page.headers["cache-control"] == "no-store"


def test_the_admin_changes_a_role_and_removes_a_member() -> None:
    client, db = _client()
    changed = client.post("/hotel/staff/u2/role", data={"role": "content_moderator"})
    assert (changed.status_code, _roles(db)["u2"]) == (303, "content_moderator")

    client.post("/hotel/staff/u2/remove")
    assert "u2" not in _roles(db)


@pytest.mark.parametrize(
    ("path", "form", "status"),
    [
        ("/hotel/staff/me/role", {"role": "content_creator"}, 409),  # their own
        ("/hotel/staff/me/remove", {}, 409),
        ("/hotel/staff/u2/role", {"role": "owner"}, 422),
        ("/hotel/staff/invite", {"role": "owner"}, 422),
    ],
)
def test_the_admin_cant_change_themselves_or_make_up_a_role(
    path: str, form: dict[str, str], status: int
) -> None:
    client, db = _client()
    assert client.post(path, data=form).status_code == status
    assert db.writes == []


def test_another_hotels_member_is_out_of_reach() -> None:
    client, db = _client()
    client.post("/hotel/staff/u3/role", data={"role": "hotel_admin"})
    client.post("/hotel/staff/u3/remove")
    assert _roles(db)["u3"] == "content_creator"


@pytest.mark.parametrize("role", ["content_moderator", "content_creator"])
@pytest.mark.parametrize(
    ("method", "path", "form"),
    [
        ("get", "/hotel/staff", None),
        ("post", "/hotel/staff/invite", {"role": "hotel_admin"}),
        ("post", "/hotel/staff/u2/role", {"role": "hotel_admin"}),
        ("post", "/hotel/staff/u2/remove", {}),
    ],
)
def test_other_roles_cant_manage_the_team(
    role: str, method: str, path: str, form: dict[str, str] | None
) -> None:
    client, db = _client(role)
    response = client.request(method.upper(), path, data=form)

    assert response.status_code == 403
    assert db.writes == []
    assert 'href="/hotel/staff"' not in client.get("/hotel").text
