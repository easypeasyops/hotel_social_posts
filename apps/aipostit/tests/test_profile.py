"""Each signed-in account has a profile page in its own area: /hotel/profile for hotel staff
(Turkish), /dashboard/profile for operators. It shows the account's name, email, role and, for
staff, hotel."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.database import get_supabase
from app.main import create_app
from tests.fakes import FakeDB

STAFF = SimpleNamespace(
    id="staff-1", email="ayse@lagoon.test", app_metadata={},
    user_metadata={"full_name": " Ayşe Kaya "},
)  # fmt: skip
OPERATOR = SimpleNamespace(
    id="op-1", email="op@example.com", app_metadata={"role": "operator"}, user_metadata={}
)


def _client(user: SimpleNamespace) -> TestClient:
    db = FakeDB(
        hotels=[{"id": "hotel-1", "name": "Lagoon Bay", "slug": "lagoon-bay"}],
        hotel_members=[{"user_id": "staff-1", "hotel_id": "hotel-1", "role": "content_moderator"}],
    )
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False)


def test_staff_see_their_name_email_hotel_and_role() -> None:
    page = _client(STAFF).get("/hotel/profile")

    assert page.status_code == 200
    for shown in ("Ayşe Kaya", "ayse@lagoon.test", "Lagoon Bay", "İçerik moderatörü"):
        assert shown in page.text


def test_an_operator_sees_their_profile_on_the_dashboard() -> None:
    page = _client(OPERATOR).get("/dashboard/profile")

    assert page.status_code == 200
    assert "op@example.com" in page.text and "Not added yet" in page.text


def test_each_area_keeps_its_own_profile() -> None:
    assert _client(STAFF).get("/dashboard/profile").status_code == 403
    assert _client(OPERATOR).get("/hotel/profile").status_code == 403
