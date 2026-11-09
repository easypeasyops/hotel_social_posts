"""An account uploads its own profile photo on its profile page: it is kept as a small square
WebP in the private bucket, shown only to that account (/account/photo) in the user menu and on
the profile, ahead of a photo Google gave; it can be removed again."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import profile_photo
from app.account import menu
from app.auth.dependencies import get_current_user
from app.database import get_supabase
from app.main import create_app
from tests.fakes import NAMED, FakeDB
from tests.test_profile import FakeAdmin

PATH = ("hotel-assets", "avatars/staff-1.webp")


def _png(size: tuple[int, int] = (600, 300)) -> bytes:
    out = BytesIO()
    Image.new("RGB", size, "purple").save(out, "PNG")
    return out.getvalue()


def _client(metadata: dict | None = None, role: str | None = None):
    db = FakeDB(
        hotel_members=[{"user_id": "staff-1", "hotel_id": "hotel-1", "role": "hotel_admin"}]
    )
    admin = FakeAdmin()
    db.auth = SimpleNamespace(admin=admin)  # type: ignore[attr-defined]
    user = SimpleNamespace(
        id="staff-1" if role is None else "op-1", email="a@x.test",
        app_metadata={"role": role} if role else {}, user_metadata={**NAMED, **(metadata or {})},
    )  # fmt: skip
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False), db, admin


def test_an_upload_is_kept_as_a_small_square_webp() -> None:
    client, db, admin = _client()
    sent = client.post("/account/photo", files={"photo": ("me.png", _png(), "image/png")})

    assert sent.headers["location"] == "/hotel/profile?photo=saved"
    with Image.open(BytesIO(db.storage.files[PATH])) as stored:
        assert (stored.format, stored.size) == ("WEBP", (256, 256))
    assert admin.updated[0][1]["user_metadata"]["photo_version"] > 0


def test_an_operator_goes_back_to_the_dashboard_profile() -> None:
    client, _, _ = _client(role="operator")
    sent = client.post("/account/photo", files={"photo": ("me.png", _png(), "image/png")})

    assert sent.headers["location"] == "/dashboard/profile?photo=saved"


@pytest.mark.parametrize("data", [b"not an image", b"GIF89a" + b"\0" * 20])
def test_a_file_that_isnt_a_photo_is_refused(data: bytes) -> None:
    client, db, admin = _client()
    sent = client.post("/account/photo", files={"photo": ("x.png", data, "image/png")})

    assert sent.headers["location"] == "/hotel/profile?photo=invalid"
    assert db.storage.files == {} and admin.updated == []


def test_a_photo_over_the_limit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profile_photo, "MAX_UPLOAD_BYTES", 100)
    client, db, _ = _client()
    sent = client.post("/account/photo", files={"photo": ("me.png", _png(), "image/png")})

    assert sent.headers["location"] == "/hotel/profile?photo=invalid" and db.storage.files == {}


def test_the_photo_is_served_to_its_account_and_can_be_removed() -> None:
    client, db, admin = _client({"photo_version": 7})
    db.storage.files[PATH] = b"webp"

    shown = client.get("/account/photo?v=7")
    assert (shown.status_code, shown.content) == (200, b"webp")
    assert shown.headers["content-type"] == "image/webp"

    assert (
        client.post("/account/photo/remove").headers["location"] == "/hotel/profile?photo=removed"
    )
    assert db.storage.files == {}
    assert admin.updated == [("staff-1", {"user_metadata": {"photo_version": None}})]


def test_without_a_photo_there_is_nothing_to_serve() -> None:
    client, _, _ = _client()

    assert client.get("/account/photo").status_code == 404


def test_the_uploaded_photo_comes_before_googles() -> None:
    google = {"avatar_url": "https://lh3.googleusercontent.com/a/me"}
    user = SimpleNamespace(email="a@x.test", user_metadata={**google, "photo_version": 9})

    assert menu(user)["avatar_url"] == "/account/photo?v=9"
    assert (
        menu(SimpleNamespace(email="a@x.test", user_metadata=google))["avatar_url"]
        == (google["avatar_url"])
    )


def test_an_account_with_no_access_cant_upload() -> None:
    client, db, _ = _client()
    db.rows["hotel_members"] = []
    sent = client.post("/account/photo", files={"photo": ("me.png", _png(), "image/png")})

    assert sent.status_code == 403 and db.storage.files == {}
