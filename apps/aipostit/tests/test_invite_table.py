"""Both team pages list the hotel's recorded invites: status derived from the row, "email not
sent" on a pending invite never emailed, and a pending invite's link, rebuilt from its row,
which signs up. Only the operator and the hotel's admin see them."""

from datetime import UTC, datetime, timedelta
from html import unescape
from types import SimpleNamespace
from typing import Any
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user, require_operator
from app.database import get_supabase
from app.hotels.invites import invite_status
from app.main import create_app
from tests.fakes import NAMED, FakeDB
from tests.test_recorded_invite_signup import supabase_with
from tests.test_staff_signup import (
    sign_up,
    store,  # noqa: F401 (the fixture)
)

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
HOTEL = {"id": "hotel-1", "name": "Ege Konak", "slug": "ege-konak"}


def invite(email: str, **overrides: Any) -> dict[str, Any]:
    return {
        "id": f"id-{email.split('@')[0]}",
        "hotel_id": "hotel-1",
        "role": "content_creator",
        "email": email,
        "invited_by_email": "op@example.com",
        "created_at": "2026-11-08T10:00:00+00:00",
        "expires_at": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
        "last_sent_at": "2026-11-08T10:00:01+00:00",
        "accepted_at": None,
        "revoked_at": None,
        **overrides,
    }


def invites() -> list[dict[str, Any]]:
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    return [
        invite("sent@example.com"),
        invite("unsent@example.com", last_sent_at=None),
        invite("joined@example.com", accepted_at="2026-11-08T11:00:00+00:00"),
        invite("lapsed@example.com", expires_at=past, last_sent_at=None),
        invite("taken-back@example.com", revoked_at="2026-11-08T12:00:00+00:00"),
        invite("other-hotel@example.com", hotel_id="hotel-2"),
    ]


@pytest.mark.parametrize(
    ("fields", "status"),
    [
        ({}, "pending"),
        ({"accepted_at": "2026-11-09T11:00:00+00:00"}, "accepted"),
        ({"revoked_at": "2026-11-09T11:00:00+00:00"}, "revoked"),
        ({"expires_at": "2026-11-09T12:00:00+00:00"}, "expired"),  # at NOW
        ({"expires_at": "2026-11-09T12:00:01+00:00"}, "pending"),
    ],
)
def test_the_status_comes_from_the_row(fields: dict[str, str], status: str) -> None:
    assert invite_status(invite("a@example.com", **fields), NOW) == status


def dashboard(db: FakeDB) -> str:
    app = create_app()
    app.dependency_overrides[require_operator] = lambda: SimpleNamespace(
        user_metadata=NAMED, email="op@example.com"
    )
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app).get("/dashboard/hotels/hotel-1").text


def team_page(role: str, db: FakeDB) -> Any:
    db.rows["hotel_members"] = [
        {"user_id": "me", "hotel_id": "hotel-1", "email": "me@example.com", "role": role}
    ]
    app = create_app()
    me = SimpleNamespace(user_metadata=NAMED, id="me", email="me@example.com", app_metadata={})
    app.dependency_overrides[get_current_user] = lambda: me
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False).get("/hotel/staff")


def links(page: str) -> dict[str, str]:
    """Each pending invite's link, by its id: on its copy button, never shown as text."""
    found = {}
    for part in page.split(' data-copy="')[1:]:
        link, button = part.split(">", 1)[0].split('"', 1)
        if ' data-invite="' in button:
            found[button.split(' data-invite="', 1)[1].split('"', 1)[0]] = unescape(link)
    return found


@pytest.mark.parametrize(
    ("page", "not_sent", "statuses"),
    [
        (lambda db: dashboard(db), "email not sent", ["accepted 2026-11-08", "expired", "revoked"]),
        (
            lambda db: team_page("hotel_admin", db).text,
            "e-posta gönderilmedi",
            ["kabul edildi 2026-11-08", "süresi doldu", "iptal edildi"],
        ),
    ],
)
def test_each_page_lists_its_hotels_invites_with_links_for_pending_ones(
    page: Any, not_sent: str, statuses: list[str]
) -> None:
    text = page(FakeDB(hotels=[HOTEL], staff_invites=invites()))

    assert "taken-back@example.com" in text and "other-hotel@example.com" not in text
    assert set(links(text)) == {"id-sent", "id-unsent"}
    assert text.count(not_sent) == 1  # the pending one never emailed, not the expired one
    assert all(status in text for status in statuses)
    assert "op@example.com" in text


@pytest.mark.usefixtures("store")
def test_a_shown_link_signs_up(monkeypatch: pytest.MonkeyPatch) -> None:
    link = links(dashboard(FakeDB(hotels=[HOTEL], staff_invites=invites())))["id-unsent"]
    supabase_with(monkeypatch, invite("unsent@example.com", last_sent_at=None))

    response = sign_up(unquote(link.split("#invite=", 1)[1]), email="unsent@example.com")
    assert (response.status_code, response.headers["location"]) == (303, "/hotel")


@pytest.mark.parametrize("role", ["content_moderator", "content_creator"])
def test_other_staff_roles_see_no_invites(role: str) -> None:
    response = team_page(role, FakeDB(hotels=[HOTEL], staff_invites=invites()))
    assert response.status_code == 403
    assert "sent@example.com" not in response.text
