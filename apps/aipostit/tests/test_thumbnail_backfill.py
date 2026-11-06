"""Photos uploaded before thumbnails existed get theirs from a task run by hand: only ready
photos without one, and a photo that can't be read is skipped, never failed."""

from io import BytesIO
from typing import Any

import pytest
from PIL import Image

from app.assets.service import STORAGE_BUCKET
from app.jobs.tasks import backfill_thumbnails_task
from tests.fakes import FakeDB


def _photo() -> bytes:
    out = BytesIO()
    Image.new("RGB", (1600, 1200), "teal").save(out, "JPEG")
    return out.getvalue()


def _asset(asset_id: str, filename: str, **extra: Any) -> dict[str, Any]:
    path = f"h1/{asset_id}/{filename}"
    return {"id": asset_id, "hotel_id": "h1", "filename": filename, "status": "ready",
            "storage_path": path, "thumbnail_path": None, **extra}  # fmt: skip


def _run(
    monkeypatch: pytest.MonkeyPatch, *assets: dict[str, Any], files: dict[str, bytes]
) -> tuple[FakeDB, int]:
    db = FakeDB(assets=list(assets))
    for path, data in files.items():
        db.storage.files[(STORAGE_BUCKET, path)] = data
    monkeypatch.setattr("app.database.get_supabase", lambda: db)
    return db, backfill_thumbnails_task.run()


def test_old_photos_get_their_thumbnails(monkeypatch: pytest.MonkeyPatch) -> None:
    db, made = _run(monkeypatch, _asset("a1", "pool.jpg"), _asset("a2", "Lobby.PNG"),
              files={"h1/a1/pool.jpg": _photo(), "h1/a2/Lobby.PNG": _photo()})  # fmt: skip

    assert made == 2
    assert [a["thumbnail_path"] for a in db.rows["assets"]] == [
        "thumbnails/h1/a1.webp",
        "thumbnails/h1/a2.webp",
    ]
    thumbnail = Image.open(BytesIO(db.storage.files[(STORAGE_BUCKET, "thumbnails/h1/a1.webp")]))
    assert (thumbnail.format, thumbnail.size) == ("WEBP", (480, 360))


def test_it_leaves_everything_else_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    db, made = _run(
        monkeypatch,
        _asset("a1", "pool.jpg", thumbnail_path="thumbnails/h1/a1.webp"),  # has one already
        _asset("a2", "drone.mp4"),  # a video: no thumbnail
        _asset("a3", "spa.jpg", status="processing"),  # the upload's own task will do it
        files={},
    )
    assert made == 0
    assert db.storage.uploads == []
    assert [a["thumbnail_path"] for a in db.rows["assets"]] == ["thumbnails/h1/a1.webp", None, None]


def test_a_photo_it_cant_read_is_skipped_and_stays_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    db, made = _run(
        monkeypatch,
        _asset("a1", "broken.jpg"),  # not an image
        _asset("a2", "missing.jpg"),  # the file is gone from storage
        _asset("a3", "pool.jpg"),
        files={"h1/a1/broken.jpg": b"not a jpeg", "h1/a3/pool.jpg": _photo()},
    )
    assert made == 1
    assert [(a["status"], a["thumbnail_path"]) for a in db.rows["assets"]] == [
        ("ready", None),
        ("ready", None),
        ("ready", "thumbnails/h1/a3.webp"),
    ]
