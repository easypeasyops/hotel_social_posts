"""The photo purge deletes the profile photos no one can see any more: of accounts deleted from
Supabase and of accounts with no access. Staff and operators keep theirs; an account Supabase
can't be asked about is kept, and the purge then fails so the Job's alert fires."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import yaml
from supabase_auth.errors import AuthApiError

from app import database, profile_photo
from app.jobs import purge_photos
from tests.fakes import FakeDB

BUCKET = "hotel-assets"


class Admin:
    def __init__(self, users: dict[str, Any]) -> None:
        self.users = users
        self.updated: list[tuple[str, dict]] = []

    def get_user_by_id(self, user_id: str) -> SimpleNamespace:
        found = self.users.get(user_id)
        if found is None:
            raise AuthApiError("User not found", 404, "user_not_found")
        if isinstance(found, Exception):
            raise found
        return SimpleNamespace(user=found)

    def update_user_by_id(self, user_id: str, attributes: dict) -> None:
        self.updated.append((user_id, attributes))


def _db(*owners: str, users: dict[str, Any] | None = None) -> tuple[FakeDB, Admin]:
    db = FakeDB(hotel_members=[{"user_id": "staff", "hotel_id": "hotel-1"}])
    admin = Admin(users or {})
    db.auth = SimpleNamespace(admin=admin)  # type: ignore[attr-defined]
    for owner in owners:
        db.storage.files[(BUCKET, f"avatars/{owner}.webp")] = b"webp"
    db.storage.files[(BUCKET, "hotel-1/a1/pool.jpg")] = b"jpg"  # not a profile photo
    return db, admin


def purge_orphan_photos(db: FakeDB) -> int:
    return profile_photo.purge_orphan_photos(cast(Any, db))


def _left(db: FakeDB) -> set[str]:
    return {path for _, path in db.storage.files}


def test_photos_no_one_can_see_are_deleted_and_the_rest_kept() -> None:
    db, admin = _db(
        "staff", "operator", "deleted", "removed",
        users={"operator": SimpleNamespace(app_metadata={"role": "operator"}),
               "removed": SimpleNamespace(app_metadata={})},
    )  # fmt: skip

    assert purge_orphan_photos(db) == 2
    assert _left(db) == {"avatars/staff.webp", "avatars/operator.webp", "hotel-1/a1/pool.jpg"}
    # The removed account still exists: it shows initials if a hotel takes it back.
    assert admin.updated == [("removed", {"user_metadata": {"photo_version": None}})]


def test_an_account_supabase_cant_be_asked_about_is_kept_and_the_purge_fails() -> None:
    db, _ = _db(
        "flaky", "deleted",
        users={"flaky": AuthApiError("Service unavailable", 503, None)},
    )  # fmt: skip

    with pytest.raises(RuntimeError, match="1 profile photos"):
        purge_orphan_photos(db)
    assert "avatars/flaky.webp" in _left(db) and "avatars/deleted.webp" not in _left(db)


def test_every_page_of_the_listing_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profile_photo, "LIST_PAGE", 2)
    db, _ = _db("d1", "d2", "d3", "d4", "d5")

    assert purge_orphan_photos(db) == 5


@pytest.mark.parametrize(("outcome", "code"), [(None, 0), (RuntimeError("no"), 1)])
def test_the_job_exits_0_when_it_worked_and_1_when_it_failed(
    monkeypatch: pytest.MonkeyPatch, outcome: Exception | None, code: int
) -> None:
    monkeypatch.setattr(database, "get_supabase", lambda: object())

    def purge(_: object) -> int:
        if outcome:
            raise outcome
        return 0

    monkeypatch.setattr(profile_photo, "purge_orphan_photos", purge)
    assert purge_photos.main() == code


def test_prod_runs_the_purge_daily_and_staging_doesnt() -> None:
    deploy = Path(__file__).parent.parent / "deploy"
    service = yaml.safe_load((deploy / "service/values.yaml").read_text())
    staging = yaml.safe_load((deploy / "envs/staging.yaml").read_text())

    job = service["cronJobs"]["purge-photos"]
    assert job["command"] == ["python", "-m", "app.jobs.purge_photos"]
    assert job["schedule"] == "30 4 * * *"
    assert "purge-photos" in staging["cronJobs"] and staging["cronJobs"]["purge-photos"] is None
