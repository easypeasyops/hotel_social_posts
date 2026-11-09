"""Sign-up asks for a full name; an account made before it did is asked once, on its profile
page, before any other page (GET) opens, and then goes on to its area's home."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.database import get_supabase
from app.main import create_app
from tests.fakes import FakeDB
from tests.test_profile import FakeAdmin
from tests.test_staff_signup import sign_up, supabase_with

NAMELESS_STAFF = SimpleNamespace(id="staff-1", email="s@x.test", app_metadata={}, user_metadata={})
NAMELESS_OPERATOR = SimpleNamespace(
    id="op-1", email="op@x.test", app_metadata={"role": "operator"}, user_metadata={}
)
AREAS = [
    (NAMELESS_STAFF, "/hotel", "/hotel/profile", "/hotel"),
    (NAMELESS_OPERATOR, "/dashboard/hotels", "/dashboard/profile", "/dashboard/hotels"),
]


def _client(user: SimpleNamespace) -> TestClient:
    db = FakeDB(
        hotels=[{"id": "hotel-1", "name": "Lagoon Bay", "slug": "lagoon-bay"}],
        hotel_members=[{"user_id": "staff-1", "hotel_id": "hotel-1", "role": "hotel_admin"}],
    )
    db.auth = SimpleNamespace(admin=FakeAdmin())  # type: ignore[attr-defined]
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False)


@pytest.mark.parametrize(("user", "page", "profile", "home"), AREAS)
def test_an_account_without_a_name_is_asked_for_one_first(
    user: SimpleNamespace, page: str, profile: str, home: str
) -> None:
    client = _client(user)

    sent = client.get(page)
    assert sent.status_code == 303 and sent.headers["location"] == f"{profile}?name=required"
    asked = client.get(f"{profile}?name=required")
    assert asked.status_code == 200 and 'name="first" value="1"' in asked.text

    saved = client.post(profile, data={"name": "Ayşe Kaya", "first": "1"})
    assert saved.status_code == 303 and saved.headers["location"] == home


def test_a_form_post_is_not_held_back_by_the_name_step() -> None:
    response = _client(NAMELESS_STAFF).post("/hotel/staff/u2/role", data={"role": "nope"})

    assert response.status_code == 422  # the route's own answer, not a redirect


def test_sign_up_refuses_a_blank_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _, admin = supabase_with(monkeypatch)
    page = sign_up(full_name="   ")

    assert page.status_code == 422 and "Enter your full name" in page.text
    assert admin.created == []
