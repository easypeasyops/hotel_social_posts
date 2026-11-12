"""Hotel staff sign up from an invite link, whose token points at a pending staff_invites row.
/signup makes the account with the service role, ties it to that hotel and signs it in; without
a valid invite nothing is made."""

import base64
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import fakeredis
import pytest
from fastapi.testclient import TestClient
from supabase_auth.errors import AuthApiError

from app.auth import sessions, signup
from app.auth.upload_tokens import create_recorded_invite_token, create_token, read_recorded_invite
from app.main import create_app
from tests.fakes import FakeDB

HOTEL = {"id": "hotel-1", "name": "Lagoon Bay", "slug": "lagoon-bay"}
TOKENS = {"access_token": "access", "refresh_token": "refresh", "expires_at": 1_900_000_000}
LATER = datetime.now(UTC) + timedelta(days=7)
INVITES = [
    {
        "id": invite_id,
        "hotel_id": hotel_id,
        "role": "hotel_admin",
        "email": "staff@example.com",
        "expires_at": LATER.isoformat(),
        "accepted_at": None,
        "revoked_at": None,
    }
    for invite_id, hotel_id in [("invite-1", "hotel-1"), ("invite-2", "deleted-hotel")]
]


def invite_token(hotel_id: str = "hotel-1", invite_id: str = "invite-1", at=LATER) -> str:
    return create_recorded_invite_token(hotel_id, invite_id, "staff@example.com", at)


class FakeAdmin:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.created: list[dict[str, Any]] = []

    def create_user(self, attributes: dict[str, Any]) -> SimpleNamespace:
        if self.error:
            raise self.error
        self.created.append(attributes)
        return SimpleNamespace(user=SimpleNamespace(id="new-user", email=attributes["email"]))


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Iterator[fakeredis.FakeRedis]:
    redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(sessions, "get_session_store", lambda: redis)
    yield redis


def supabase_with(
    monkeypatch: pytest.MonkeyPatch, error: Exception | None = None
) -> tuple[FakeDB, FakeAdmin]:
    db = FakeDB(hotels=[HOTEL], staff_invites=[dict(row) for row in INVITES])
    admin = FakeAdmin(error)
    db.auth = SimpleNamespace(admin=admin)  # type: ignore[attr-defined]
    monkeypatch.setattr(signup, "get_supabase", lambda: db)
    sign_in = SimpleNamespace(
        sign_in_with_password=lambda credentials: SimpleNamespace(session=SimpleNamespace(**TOKENS))
    )
    monkeypatch.setattr(signup, "get_supabase_anon", lambda: SimpleNamespace(auth=sign_in))
    return db, admin


def sign_up(invite: str | None = None, **overrides: str) -> Any:
    form = {
        "invite": invite_token() if invite is None else invite,
        "full_name": "Ayşe Kaya",
        "email": "staff@example.com",
        "password": "lagoon-bay-2026",
        "password_confirmation": "lagoon-bay-2026",
        **overrides,
    }
    return TestClient(create_app(), follow_redirects=False).post("/signup", data=form)


def test_an_invite_makes_a_staff_account_for_its_hotel_and_signs_it_in(
    monkeypatch: pytest.MonkeyPatch, store: fakeredis.FakeRedis
) -> None:
    db, admin = supabase_with(monkeypatch)
    response = sign_up()

    assert (response.status_code, response.headers["location"]) == (303, "/hotel")
    assert admin.created == [
        {
            "email": "staff@example.com",
            "password": "lagoon-bay-2026",
            "email_confirm": True,
            "user_metadata": {"full_name": "Ayşe Kaya"},
        }
    ]
    assert db.written("hotel_members") == [
        {
            "user_id": "new-user",
            "hotel_id": "hotel-1",
            "email": "staff@example.com",
            "role": "hotel_admin",
        }
    ]
    session_id = response.cookies[sessions.SESSION_COOKIE]
    assert store.get(f"web-session:{session_id}") is not None


@pytest.mark.parametrize(
    "invite",
    [
        "",
        "not-a-token",
        create_token("hotel-1", "hotel-media-upload", 60),  # an upload link isn't an invite
        create_token("hotel-1", "staff-invite", 60),  # an invite from before invites were recorded
        create_token("hotel-1", "staff-invite:content_creator", 60),
        invite_token(at=datetime.now(UTC)),  # expired
        invite_token("deleted-hotel", "invite-2"),
    ],
)
def test_without_a_valid_invite_nothing_is_made(
    invite: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, admin = supabase_with(monkeypatch)
    response = sign_up(invite)

    assert response.status_code == 400
    assert "invite link is invalid or has expired" in response.text
    assert (admin.created, db.writes) == ([], [])


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"password": "short", "password_confirmation": "short"}, "at least 8 characters"),
        ({"password_confirmation": "something-else"}, "do not match"),
    ],
)
def test_a_bad_password_keeps_the_invite_and_email(
    overrides: dict[str, str], message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, admin = supabase_with(monkeypatch)
    response = sign_up(**overrides)

    assert response.status_code == 422
    assert message in response.text
    assert 'value="staff@example.com"' in response.text
    assert admin.created == []


def test_an_existing_email_is_told_so(monkeypatch: pytest.MonkeyPatch) -> None:
    error = AuthApiError(
        "A user with this email address has already been registered", 422, "email_exists"
    )
    db, _ = supabase_with(monkeypatch, error)
    response = sign_up()

    assert response.status_code == 409
    assert "already exists" in response.text
    assert db.written("hotel_members") == []


def test_the_page_asks_for_an_invite() -> None:
    page = TestClient(create_app()).get("/signup")
    assert page.status_code == 200
    assert "needs an invite link" in page.text
    assert page.headers["cache-control"] == "no-store"


def test_the_email_an_invite_names_cant_be_changed() -> None:
    encoded, signature = invite_token().split(".")
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    forged = base64.urlsafe_b64encode(json.dumps({**payload, "email": "b@x.test"}).encode())
    assert read_recorded_invite(f"{forged.rstrip(b'=').decode()}.{signature}") is None
