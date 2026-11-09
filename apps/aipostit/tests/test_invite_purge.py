"""tasks.purge_ended_invites deletes each hotel's invites that ended (the earliest of
accepted_at, revoked_at and expires_at) more than its invite_retention_days ago. Pending
invites stay; one hotel failing doesn't stop the others; the logs name no email."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.hotels.invites import purge_ended_invites
from app.jobs import tasks
from tests.fakes import FakeDB, FakeQuery

NOW = datetime(2026, 11, 9, 3, 0, tzinfo=UTC)


def at(days: float) -> str:
    """NOW plus this many days, in whole seconds (the fake compares ISO strings)."""
    return (NOW + timedelta(days=days)).replace(microsecond=0).isoformat()


def invite(name: str, hotel_id: str = "hotel-1", **times: str | None) -> dict[str, Any]:
    return {"id": name, "hotel_id": hotel_id, "email": f"{name}@guest.example",
            "accepted_at": None, "revoked_at": None, "expires_at": at(7), **times}  # fmt: skip


def ended(row: dict[str, Any]) -> datetime | None:
    """least(accepted_at, revoked_at, expires_at) for an invite that has ended, else None."""
    times = [datetime.fromisoformat(row[c]) for c in ("accepted_at", "revoked_at") if row[c]]
    expires = datetime.fromisoformat(row["expires_at"])
    if not times and expires > NOW:
        return None  # pending
    return min([*times, expires])


# Retention 30 days, so the cutoff is NOW - 30 days.
CASES = [
    invite("accepted-long-ago", accepted_at=at(-40), expires_at=at(20)),  # not expired yet
    invite("accepted-lately", accepted_at=at(-10), expires_at=at(-3)),
    invite("revoked-long-ago", revoked_at=at(-31), expires_at=at(-25)),
    invite("revoked-lately", revoked_at=at(-29), expires_at=at(-20)),
    invite("expired-long-ago", expires_at=at(-45)),
    invite("expired-lately", expires_at=at(-2)),
    invite("expired-at-cutoff", expires_at=at(-30)),  # not before it: kept one more day
    invite("pending"),
    invite("pending-far-future", expires_at=at(400)),
]


def test_the_three_deletes_match_the_least_of_the_three_times() -> None:
    db = FakeDB(hotels=[{"id": "hotel-1", "invite_retention_days": 30}], staff_invites=list(CASES))

    assert purge_ended_invites(db, NOW) == 3
    cutoff = NOW - timedelta(days=30)
    expected = [r["id"] for r in CASES if not ((end := ended(r)) and end < cutoff)]
    assert [r["id"] for r in db.rows["staff_invites"]] == expected
    assert {"pending", "pending-far-future", "accepted-lately"} <= set(expected)
    assert "accepted-long-ago" not in expected  # by accepted_at + 30, not kept until expiry


def test_each_hotel_keeps_ended_invites_for_its_own_days() -> None:
    db = FakeDB(
        hotels=[{"id": "short", "invite_retention_days": 7},
                {"id": "long", "invite_retention_days": 180}],
        staff_invites=[invite("a", "short", expires_at=at(-10)),
                       invite("b", "long", expires_at=at(-10))],
    )  # fmt: skip
    assert purge_ended_invites(db, NOW) == 1
    assert [r["id"] for r in db.rows["staff_invites"]] == ["b"]


def test_one_hotel_failing_still_purges_the_others_then_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    db = FakeDB(
        hotels=[{"id": "broken", "invite_retention_days": 7},
                {"id": "fine", "invite_retention_days": 7}],
        staff_invites=[invite("a", "broken", expires_at=at(-10)),
                       invite("b", "fine", expires_at=at(-10))],
    )  # fmt: skip
    execute = FakeQuery.execute

    def failing_for_broken(query: FakeQuery) -> Any:
        if query.table == "staff_invites" and ("hotel_id", "broken") in query.equal:
            raise RuntimeError("database unavailable")
        return execute(query)

    monkeypatch.setattr(FakeQuery, "execute", failing_for_broken)
    with caplog.at_level(logging.INFO), pytest.raises(RuntimeError, match="1 hotels"):
        purge_ended_invites(db, NOW)

    assert [r["id"] for r in db.rows["staff_invites"]] == ["a"]
    assert "Could not purge the ended invites of hotel broken" in caplog.text


def test_the_logs_give_counts_and_never_an_email(caplog: pytest.LogCaptureFixture) -> None:
    db = FakeDB(hotels=[{"id": "hotel-1", "invite_retention_days": 30},
                        {"id": "hotel-2", "invite_retention_days": 30}],
                staff_invites=list(CASES))  # fmt: skip
    with caplog.at_level(logging.INFO):
        purge_ended_invites(db, NOW)

    assert "Purged 3 ended invites of hotel hotel-1" in caplog.text
    assert "hotel-2" not in caplog.text  # nothing deleted there: no line
    assert "Purged 3 ended invites across 2 hotels" in caplog.text
    assert "@" not in caplog.text


def test_the_task_is_registered_under_its_name(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDB(hotels=[], staff_invites=[])
    monkeypatch.setattr("app.database.get_supabase", lambda: db)
    assert tasks.celery_app.tasks["tasks.purge_ended_invites"].run() == 0
