"""An operator sees a hotel's staff accounts on its dashboard page, changes their roles and can
remove one, which takes that account's access away at once."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import require_operator
from app.database import get_supabase
from app.main import create_app
from tests.fakes import FakeDB

HOTEL = {"id": "hotel-1", "name": "Lagoon Bay", "slug": "lagoon-bay"}
HOSTILE = "x'+alert(1)+'@example.com"  # an email a staff member could sign up with


def members() -> list[dict[str, Any]]:
    return [
        {
            "user_id": "u1",
            "hotel_id": "hotel-1",
            "email": "anna@example.com",
            "role": "hotel_admin",
        },
        {"user_id": "u2", "hotel_id": "hotel-1", "email": HOSTILE, "role": "content_creator"},
        {
            "user_id": "u3",
            "hotel_id": "hotel-2",
            "email": "other@example.com",
            "role": "hotel_admin",
        },
    ]


def operator(db: FakeDB) -> TestClient:
    app = create_app()
    app.dependency_overrides[require_operator] = lambda: object()
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False)


def test_the_hotel_page_lists_its_own_staff() -> None:
    page = operator(FakeDB(hotels=[HOTEL], hotel_members=members())).get(
        "/dashboard/hotels/hotel-1"
    )

    assert page.status_code == 200
    assert "anna@example.com" in page.text
    assert "other@example.com" not in page.text
    # The email reaches the confirm() as a JSON string, so a quote in it can't end the string.
    assert "x\\u0027+alert(1)+\\u0027@example.com" in page.text
    assert "confirm('Remove x'" not in page.text


def test_remove_takes_one_member_of_this_hotel_away() -> None:
    db = FakeDB(hotels=[HOTEL], hotel_members=members())
    response = operator(db).post("/dashboard/hotels/hotel-1/staff/u1/remove")

    assert (response.status_code, response.headers["location"]) == (
        303,
        "/dashboard/hotels/hotel-1?done=removed#members",
    )
    assert [m["user_id"] for m in db.rows["hotel_members"]] == ["u2", "u3"]


def test_remove_cant_reach_another_hotels_member() -> None:
    db = FakeDB(hotels=[HOTEL], hotel_members=members())
    operator(db).post("/dashboard/hotels/hotel-1/staff/u3/remove")
    assert [m["user_id"] for m in db.rows["hotel_members"]] == ["u1", "u2", "u3"]


def roles(db: FakeDB) -> dict[str, str]:
    return {m["user_id"]: m["role"] for m in db.rows["hotel_members"]}


def test_the_operator_changes_a_members_role() -> None:
    db = FakeDB(hotels=[HOTEL], hotel_members=members())
    response = operator(db).post(
        "/dashboard/hotels/hotel-1/staff/u1/role", data={"role": "content_moderator"}
    )

    assert response.status_code == 303
    assert roles(db) == {"u1": "content_moderator", "u2": "content_creator", "u3": "hotel_admin"}


@pytest.mark.parametrize(("path", "role"), [("u3", "content_creator"), ("u1", "owner")])
def test_a_role_change_cant_reach_another_hotel_or_make_up_a_role(path: str, role: str) -> None:
    db = FakeDB(hotels=[HOTEL], hotel_members=members())
    operator(db).post(f"/dashboard/hotels/hotel-1/staff/{path}/role", data={"role": role})
    assert roles(db) == {"u1": "hotel_admin", "u2": "content_creator", "u3": "hotel_admin"}
