"""A hotel admin edits the hotel's details at /hotel/details: name, location, contact email,
description and channels. The slug, tier and Buffer profiles stay with operators, and other
roles are refused."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.database import get_supabase
from app.main import create_app
from tests.fakes import NAMED, FakeDB

FORM = {"name": "Ege Konak Otel", "location": "Ayvalık", "contact_email": "info@egekonak.test",
        "description": "Deniz kenarında", "channels": ["instagram", "tiktok"]}  # fmt: skip


def _client(role: str = "hotel_admin") -> tuple[TestClient, FakeDB]:
    db = FakeDB(
        hotels=[{"id": "hotel-1", "name": "Ege Konak", "slug": "ege-konak", "location": "Ayvalık",
                 "contact_email": "a@egekonak.test", "description": "", "tier": "growth",
                 "channels": ["instagram"]}],
        hotel_members=[{"user_id": "me", "hotel_id": "hotel-1", "role": role}],
    )  # fmt: skip
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        user_metadata=NAMED, id="me", app_metadata={}
    )
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False), db


def test_the_admin_sees_and_saves_the_details() -> None:
    client, db = _client()
    assert 'value="a@egekonak.test"' in client.get("/hotel/details").text
    assert 'href="/hotel/details"' in client.get("/hotel").text

    response = client.post("/hotel/details", data=FORM)

    assert (response.status_code, response.headers["location"]) == (
        303,
        "/hotel/details?done=saved",
    )
    hotel = db.rows["hotels"][0]
    assert {k: hotel[k] for k in FORM} == FORM
    assert (hotel["slug"], hotel["tier"]) == ("ege-konak", "growth")  # operators' to change


@pytest.mark.parametrize(
    "change", [{"name": " "}, {"contact_email": ""}, {"channels": ["myspace"]}, {"tier": "premium"}]
)
def test_a_bad_form_is_refused_and_tier_is_ignored(change: dict[str, Any]) -> None:
    client, db = _client()
    response = client.post("/hotel/details", data={**FORM, **change})

    if "tier" in change:  # not a field staff can set: saved without it
        assert db.rows["hotels"][0]["tier"] == "growth"
    else:
        assert response.status_code == 422
        assert db.writes == []


@pytest.mark.parametrize("role", ["content_moderator", "content_creator"])
def test_other_roles_cant_edit_the_details(role: str) -> None:
    client, db = _client(role)

    assert client.get("/hotel/details").status_code == 403
    assert client.post("/hotel/details", data=FORM).status_code == 403
    assert db.writes == []
    assert 'href="/hotel/details"' not in client.get("/hotel").text
