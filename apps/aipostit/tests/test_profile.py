"""Each signed-in account has a profile page in its own area: /hotel/profile for hotel staff
(Turkish), /dashboard/profile for operators. It shows the account's name, email, role and, for
staff, hotel."""

from types import SimpleNamespace

import pytest
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


class FakeAdmin:
    def __init__(self) -> None:
        self.updated: list[tuple[str, dict]] = []

    def update_user_by_id(self, user_id: str, attributes: dict) -> None:
        self.updated.append((user_id, attributes))


def _client(user: SimpleNamespace, admin: FakeAdmin | None = None) -> TestClient:
    db = FakeDB(
        hotels=[{"id": "hotel-1", "name": "Lagoon Bay", "slug": "lagoon-bay"}],
        hotel_members=[{"user_id": "staff-1", "hotel_id": "hotel-1", "role": "content_moderator"}],
    )
    db.auth = SimpleNamespace(admin=admin or FakeAdmin())  # type: ignore[attr-defined]
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
    assert "op@example.com" in page.text and 'name="name" value=""' in page.text


def test_each_area_keeps_its_own_profile() -> None:
    assert _client(STAFF).get("/dashboard/profile").status_code == 403
    assert _client(OPERATOR).get("/hotel/profile").status_code == 403


@pytest.mark.parametrize(
    ("user", "path"), [(STAFF, "/hotel/profile"), (OPERATOR, "/dashboard/profile")]
)
def test_the_name_is_saved_to_the_account_trimmed(user: SimpleNamespace, path: str) -> None:
    admin = FakeAdmin()
    saved = _client(user, admin).post(path, data={"name": "  Ayşe   Kaya "})

    assert saved.status_code == 303 and saved.headers["location"] == f"{path}?done=saved"
    assert admin.updated == [(user.id, {"user_metadata": {"full_name": "Ayşe Kaya"}})]


@pytest.mark.parametrize("name", ["   ", "x" * 101])
@pytest.mark.parametrize("path", ["/hotel/profile", "/dashboard/profile"])
def test_a_blank_or_long_name_is_refused(name: str, path: str) -> None:
    admin = FakeAdmin()
    user = STAFF if path.startswith("/hotel") else OPERATOR
    page = _client(user, admin).post(path, data={"name": name})

    assert page.status_code == 422 and 'role="alert"' in page.text
    assert admin.updated == []


def test_the_password_link_goes_to_the_accounts_own_email() -> None:
    page = _client(STAFF).get("/hotel/profile").text
    form = page.split('action="/forgot-password"', 1)[1].split("</form>", 1)[0]

    assert 'name="email" value="ayse@lagoon.test"' in form
