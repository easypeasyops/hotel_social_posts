"""How long a hotel keeps ended invites (hotels.invite_retention_days, 7 to 180 days) is set by
the operator on the dashboard's hotel form and by the hotel's admin on /hotel/details; other
fields stay as they were, and other roles can't reach either form."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user, require_operator
from app.database import get_supabase
from app.main import create_app
from tests.fakes import NAMED, FakeDB

HOTEL = {"id": "hotel-1", "name": "Ege Konak", "slug": "ege-konak", "location": "Ayvalık",
         "contact_email": "info@egekonak.test", "description": "Deniz kenarında",
         "tier": "growth", "channels": ["instagram"], "invite_retention_days": 90}  # fmt: skip
FORM = {"name": "Ege Konak", "location": "Ayvalık", "contact_email": "info@egekonak.test",
        "description": "Deniz kenarında", "channels": ["instagram"]}  # fmt: skip


def operator(db: FakeDB) -> TestClient:
    app = create_app()
    app.dependency_overrides[require_operator] = lambda: SimpleNamespace(
        user_metadata=NAMED, email="op@example.com"
    )
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False)


def staff(db: FakeDB, role: str = "hotel_admin") -> TestClient:
    db.rows["hotel_members"] = [{"user_id": "me", "hotel_id": "hotel-1", "role": role}]
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        user_metadata=NAMED, id="me", app_metadata={}
    )
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False)


def save(page: str, db: FakeDB, days: str) -> Any:
    form = {**FORM, "invite_retention_days": days}
    if page == "dashboard":
        return operator(db).post("/dashboard/hotels/hotel-1", data={**form, "tier": "growth"})
    return staff(db).post("/hotel/details", data=form)


@pytest.mark.parametrize("page", ["dashboard", "details"])
def test_each_form_saves_the_retention_and_keeps_the_rest(page: str) -> None:
    db = FakeDB(hotels=[dict(HOTEL)])
    assert save(page, db, "30").status_code == 303

    assert db.rows["hotels"][0] == {**HOTEL, "invite_retention_days": 30}


@pytest.mark.parametrize("page", ["dashboard", "details"])
@pytest.mark.parametrize("days", ["6", "181", "abc", "12.5", "-90"])
def test_a_retention_out_of_range_or_not_a_whole_number_is_refused(page: str, days: str) -> None:
    db = FakeDB(hotels=[dict(HOTEL)])
    response = save(page, db, days)

    assert response.status_code == 422
    assert db.writes == []


@pytest.mark.parametrize(
    ("client", "path", "label"),
    [
        (operator, "/dashboard/hotels/hotel-1/edit", "Keep ended invites for (days)"),
        (staff, "/hotel/details", "Biten davetleri saklama süresi (gün)"),
    ],
)
def test_each_form_shows_the_current_value(client: Any, path: str, label: str) -> None:
    page = client(FakeDB(hotels=[{**HOTEL, "invite_retention_days": 45}])).get(path).text
    assert label in page
    assert 'name="invite_retention_days" type="number" min="7" max="180"' in page
    assert 'value="45"' in page


@pytest.mark.parametrize("role", ["content_moderator", "content_creator"])
def test_other_staff_roles_cant_set_it(role: str) -> None:
    db = FakeDB(hotels=[dict(HOTEL)])
    data = {**FORM, "invite_retention_days": "30"}
    assert staff(db, role).post("/hotel/details", data=data).status_code == 403
    assert db.writes == []


@pytest.mark.parametrize("days", [None, ""])  # not sent, or sent empty (the field is required)
def test_a_form_without_a_value_leaves_it_alone(days: str | None) -> None:
    db = FakeDB(hotels=[dict(HOTEL)])
    form = {**FORM, "tier": "growth"} | ({} if days is None else {"invite_retention_days": days})
    operator(db).post("/dashboard/hotels/hotel-1", data=form)
    assert db.rows["hotels"][0]["invite_retention_days"] == 90
