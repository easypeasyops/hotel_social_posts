"""The purge-invites CronJob runs app.jobs.purge_invites: one purge, exit 0 when it worked and 1
when it raised, so a failed purge fails the Job."""

from typing import Any

import pytest

from app import database
from app.hotels import invites
from app.jobs import purge_invites


def run_with(monkeypatch: pytest.MonkeyPatch, purge: Any) -> tuple[int, list[object]]:
    calls: list[object] = []
    db = object()
    monkeypatch.setattr(database, "get_supabase", lambda: db)

    def recording(given: object) -> int:
        calls.append(given)
        return purge()

    monkeypatch.setattr(invites, "purge_ended_invites", recording)
    return purge_invites.main(), calls


def test_a_purge_that_works_exits_0_after_one_run(monkeypatch: pytest.MonkeyPatch) -> None:
    code, calls = run_with(monkeypatch, lambda: 3)
    assert code == 0 and len(calls) == 1


def test_a_purge_that_fails_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing() -> int:
        raise RuntimeError("Could not purge the ended invites of 1 hotels")

    code, calls = run_with(monkeypatch, failing)
    assert code == 1 and len(calls) == 1
