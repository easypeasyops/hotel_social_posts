"""Every signed-in page has a user menu in its top bar: the account's photo or initials and a
welcome, opening on Profile, Team for a hotel admin, and Sign out, which moved off the bar."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.account import menu
from app.auth.dependencies import get_current_user
from app.database import get_supabase
from app.main import create_app
from tests.fakes import FakeDB

STAFF = SimpleNamespace(
    id="staff-1", email="ayse@lagoon.test", app_metadata={},
    user_metadata={"full_name": "Ayşe Nur Kaya"},
)  # fmt: skip
OPERATOR = SimpleNamespace(
    id="op-1", email="op@example.com", app_metadata={"role": "operator"},
    user_metadata={"avatar_url": "https://lh3.googleusercontent.com/a/me"},
)  # fmt: skip


def _page(user: SimpleNamespace, path: str, role: str = "hotel_admin") -> str:
    db = FakeDB(
        hotels=[{"id": "hotel-1", "name": "Lagoon Bay", "slug": "lagoon-bay"}],
        hotel_members=[{"user_id": "staff-1", "hotel_id": "hotel-1", "role": role}],
    )
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_supabase] = lambda: db
    page = TestClient(app).get(path)
    assert page.status_code == 200
    return page.text


def _menu(page: str) -> str:
    return page.split("<details data-menu", 1)[1].split("</details>", 1)[0]


def test_staff_get_a_turkish_menu_with_sign_out_in_it() -> None:
    page = _page(STAFF, "/hotel")
    item = _menu(page)

    assert "Hoş geldin" in item and "Ayşe" in item and ">AK<" in item
    assert "Lagoon Bay · Otel yöneticisi" in item
    assert 'href="/hotel/profile"' in item and 'href="/hotel/staff"' in item
    assert 'action="/logout"' in item and page.count('action="/logout"') == 1
    assert '<script src="/static/menu.js" defer>' in page


def test_only_a_hotel_admin_has_team_in_the_menu() -> None:
    item = _menu(_page(STAFF, "/hotel/profile", role="content_creator"))

    assert "İçerik üreticisi" in item and 'href="/hotel/staff"' not in item


def test_an_operator_gets_an_english_menu_with_their_google_photo() -> None:
    page = _page(OPERATOR, "/dashboard/hotels")
    item = _menu(page)

    assert "Welcome" in item and ">op<" in item
    assert 'src="https://lh3.googleusercontent.com/a/me"' in item
    assert 'href="/dashboard/profile"' in item and 'action="/logout"' in item
    assert page.count('action="/logout"') == 1


@pytest.mark.parametrize(
    ("name", "email", "initials"),
    [("ayşe kaya", "a@x.test", "AK"), ("", "mehmet.y@x.test", "M"), ("", "", "?")],
)
def test_initials_come_from_the_name_or_the_email(name: str, email: str, initials: str) -> None:
    user = SimpleNamespace(email=email, user_metadata={"full_name": name})

    assert menu(user)["initials"] == initials
