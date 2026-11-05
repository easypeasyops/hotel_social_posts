"""The worker makes each uploaded photo a small upright WebP thumbnail before the photo is
ready; a file that isn't the photo it claims to be fails, and other files are ready as is."""

from io import BytesIO
from typing import Any

import pytest
from PIL import Image

from app.assets.service import STORAGE_BUCKET, delete_asset
from app.jobs.tasks import process_asset_task
from tests.fakes import FakeDB

ORIENTATION = 0x0112  # the EXIF tag; 6 means "turn 90° clockwise to show"


def _photo(size: tuple[int, int], kind: str = "JPEG", **save: Any) -> bytes:
    out = BytesIO()
    Image.new("RGB", size, "teal").save(out, kind, **save)
    return out.getvalue()


def _process(monkeypatch: pytest.MonkeyPatch, filename: str, data: bytes) -> FakeDB:
    asset = {"id": "a1", "hotel_id": "h1", "filename": filename,
             "storage_path": f"h1/a1/{filename}", "status": "processing"}  # fmt: skip
    db = FakeDB(assets=[asset])
    db.storage.files[(STORAGE_BUCKET, asset["storage_path"])] = data
    monkeypatch.setattr("app.database.get_supabase", lambda: db)
    process_asset_task.run("a1")
    return db


def _thumbnail(db: FakeDB) -> Image.Image:
    return Image.open(BytesIO(db.storage.files[(STORAGE_BUCKET, "thumbnails/h1/a1.webp")]))


def test_a_photo_gets_a_small_webp_thumbnail(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _process(monkeypatch, "Pool.JPG", _photo((4000, 3000)))

    asset = db.rows["assets"][0]
    assert (asset["status"], asset["thumbnail_path"]) == ("ready", "thumbnails/h1/a1.webp")
    thumbnail = _thumbnail(db)
    assert (thumbnail.format, thumbnail.size) == ("WEBP", (480, 360))
    assert db.storage.uploads[0][2] == {"content-type": "image/webp", "upsert": "true"}


def test_the_thumbnail_is_upright_as_the_photo_says(monkeypatch: pytest.MonkeyPatch) -> None:
    exif = Image.Exif()
    exif[ORIENTATION] = 6  # taken with the phone held upright: stored sideways
    db = _process(monkeypatch, "lobby.jpg", _photo((800, 600), exif=exif))
    assert _thumbnail(db).size == (360, 480)


def test_a_transparent_png_keeps_its_transparency(monkeypatch: pytest.MonkeyPatch) -> None:
    out = BytesIO()
    Image.new("RGBA", (100, 50), (0, 0, 0, 0)).save(out, "PNG")
    db = _process(monkeypatch, "logo.png", out.getvalue())
    thumbnail = _thumbnail(db)
    assert (thumbnail.mode, thumbnail.size) == ("RGBA", (100, 50))  # never enlarged


def test_a_file_that_isnt_a_photo_fails_for_good(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _process(monkeypatch, "beach.jpg", b"not a jpeg")
    assert db.rows["assets"][0]["status"] == "failed"
    assert db.storage.uploads == []


def test_a_video_is_ready_without_a_thumbnail(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _process(monkeypatch, "drone.mp4", b"mp4")
    asset = db.rows["assets"][0]
    assert asset["status"] == "ready" and "thumbnail_path" not in asset
    assert db.storage.uploads == []


def test_an_asset_deleted_before_processing_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeDB(assets=[])
    monkeypatch.setattr("app.database.get_supabase", lambda: db)
    process_asset_task.run("gone")
    assert db.writes == []


def test_deleting_a_photo_removes_its_thumbnail_too(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _process(monkeypatch, "pool.jpg", _photo((800, 600)))
    delete_asset(db, "a1")  # type: ignore[arg-type]
    assert db.storage.files == {} and db.rows["assets"] == []
