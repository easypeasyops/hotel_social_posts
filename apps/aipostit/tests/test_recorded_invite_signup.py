"""Sign-up from a recorded invite: the token points at a staff_invites row, which gives the
email and role, must still be pending, and works once. Older invites never read the table."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from supabase_auth.errors import AuthApiError

from app.auth import signup
from app.auth.upload_tokens import (
    STAFF_INVITE_PURPOSE,
    create_recorded_invite_token,
    create_token,
    read_recorded_invite,
)
from app.hotels.invites import claim_invite
from tests.fakes import FakeDB, FakeQuery
from tests.test_staff_signup import (
    HOTEL,
    TOKENS,
    FakeAdmin,
    sign_up,
    store,  # noqa: F401 (the fixture)
)

LATER = datetime.now(UTC) + timedelta(days=7)


def invite_row(**overrides: Any) -> dict[str, Any]:
    return {
        "id": "invite-1",
        "hotel_id": "hotel-1",
        "role": "content_moderator",
        "email": "staff@example.com",
        "expires_at": LATER.isoformat(),
        "accepted_at": None,
        "revoked_at": None,
        **overrides,
    }


def token(hotel_id: str = "hotel-1", invite_id: str = "invite-1") -> str:
    return create_recorded_invite_token(hotel_id, invite_id, "staff@example.com", LATER)


def supabase_with(
    monkeypatch: pytest.MonkeyPatch, *invites: dict[str, Any], error: Exception | None = None
) -> tuple[FakeDB, FakeAdmin]:
    db, admin = FakeDB(hotels=[HOTEL], staff_invites=list(invites)), FakeAdmin(error)
    db.auth = SimpleNamespace(admin=admin)  # type: ignore[attr-defined]
    monkeypatch.setattr(signup, "get_supabase", lambda: db)
    sign_in = SimpleNamespace(
        sign_in_with_password=lambda credentials: SimpleNamespace(session=SimpleNamespace(**TOKENS))
    )
    monkeypatch.setattr(signup, "get_supabase_anon", lambda: SimpleNamespace(auth=sign_in))
    return db, admin


@pytest.mark.usefixtures("store")
def test_a_recorded_invite_makes_staff_in_its_role_and_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, admin = supabase_with(monkeypatch, invite_row())
    response = sign_up(token(), email="Staff@Example.com")

    assert (response.status_code, response.headers["location"]) == (303, "/hotel")
    assert admin.created[0]["email"] == "Staff@Example.com"
    assert db.written("hotel_members")[0]["role"] == "content_moderator"
    assert db.rows["staff_invites"][0]["accepted_at"] is not None


@pytest.mark.parametrize(
    "row",
    [
        None,  # missing
        invite_row(revoked_at=datetime.now(UTC).isoformat()),
        invite_row(accepted_at=datetime.now(UTC).isoformat()),
        invite_row(expires_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat()),
        invite_row(hotel_id="hotel-2"),  # the token names hotel-1
    ],
)
def test_a_recorded_invite_that_isnt_pending_makes_nothing(
    row: dict[str, Any] | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, admin = supabase_with(monkeypatch, *([row] if row else []))
    response = sign_up(token())

    assert response.status_code == 400
    assert "invite link is invalid or has expired" in response.text
    assert (admin.created, db.written("hotel_members")) == ([], [])


def test_a_recorded_invite_signs_up_its_email_only(monkeypatch: pytest.MonkeyPatch) -> None:
    db, admin = supabase_with(monkeypatch, invite_row())
    response = sign_up(token(), email="someone-else@example.com")

    assert response.status_code == 403
    assert "This invite is for staff@example.com." in response.text
    assert (admin.created, db.writes) == ([], [])


@pytest.mark.usefixtures("store")
def test_a_recorded_invite_works_once(monkeypatch: pytest.MonkeyPatch) -> None:
    db, admin = supabase_with(monkeypatch, invite_row())
    assert sign_up(token()).status_code == 303
    assert sign_up(token()).status_code == 400
    assert len(admin.created) == 1


def test_of_two_racing_sign_ups_only_one_claims_the_invite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, admin = supabase_with(monkeypatch, invite_row())
    # Both passed the pending check; the other one claimed it first.
    monkeypatch.setattr(signup, "pending_invite", lambda *_: invite_row())
    assert claim_invite(db, "invite-1") is True
    response = sign_up(token())

    assert response.status_code == 400
    assert (admin.created, db.written("hotel_members")) == ([], [])
    assert claim_invite(db, "invite-1") is False


def test_a_failed_sign_up_hands_the_invite_back(monkeypatch: pytest.MonkeyPatch) -> None:
    error = AuthApiError("already registered", 422, "email_exists")
    db, _ = supabase_with(monkeypatch, invite_row(), error=error)

    assert sign_up(token()).status_code == 409
    assert db.rows["staff_invites"][0]["accepted_at"] is None


@pytest.mark.usefixtures("store")
def test_an_older_invite_never_reads_staff_invites(monkeypatch: pytest.MonkeyPatch) -> None:
    db, _ = supabase_with(monkeypatch)
    tables: list[str] = []
    table = db.table

    def recording_table(name: str) -> FakeQuery:
        tables.append(name)
        return table(name)

    monkeypatch.setattr(db, "table", recording_table)

    assert sign_up(create_token("hotel-1", STAFF_INVITE_PURPOSE, 60)).status_code == 303
    assert sign_up("not-a-token").status_code == 400
    assert "staff_invites" not in tables


def test_a_recorded_invite_token_names_its_hotel_and_row_only() -> None:
    assert read_recorded_invite(token()) == ("hotel-1", "invite-1")
    assert read_recorded_invite(create_token("hotel-1", STAFF_INVITE_PURPOSE, 60)) is None
    expired = create_recorded_invite_token("hotel-1", "invite-1", "a@x.test", datetime.now(UTC))
    assert read_recorded_invite(expired) is None
