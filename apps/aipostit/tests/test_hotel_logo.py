"""A hotel's logo: set or removed by an operator on the hotel's dashboard page and by the hotel's
admin on /hotel/details, fitted whole into a square WebP, shown only to operators and the
hotel's own staff, and purged with the hotel."""

from io import BytesIO
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import profile_photo
from app.auth.dependencies import get_current_user
from app.database import get_supabase
from app.main import create_app
from tests.fakes import NAMED, FakeDB

LOGO = ("hotel-assets", "hotel-logos/hotel-1.webp")
OPERATOR = SimpleNamespace(id="op", email="op@x.test", app_metadata={"role": "operator"},
                           user_metadata=NAMED)  # fmt: skip


def _staff(user_id: str = "me") -> SimpleNamespace:
    return SimpleNamespace(id=user_id, email="me@x.test", app_metadata={}, user_metadata=NAMED)


def _client(user: SimpleNamespace, role: str = "hotel_admin", logo_version: int | None = None):
    db = FakeDB(
        hotels=[{"id": "hotel-1", "name": "Ege Konak", "slug": "ege-konak", "location": "Ayvalık",
                 "contact_email": "a@x.test", "channels": [], "logo_version": logo_version}],
        hotel_members=[{"user_id": "me", "hotel_id": "hotel-1", "role": role},
                       {"user_id": "other", "hotel_id": "hotel-2", "role": "hotel_admin"}],
        assets=[], content_drafts=[], staff_invites=[],
    )  # fmt: skip
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False), db


def _wide_png() -> bytes:
    out = BytesIO()
    Image.new("RGB", (600, 200), "navy").save(out, "PNG")
    return out.getvalue()


def _upload(client: TestClient, path: str, data: bytes | None = None) -> Any:
    return client.post(path, files={"logo": ("logo.png", data or _wide_png(), "image/png")})


@pytest.mark.parametrize(
    ("user", "path", "back"),
    [
        (OPERATOR, "/dashboard/hotels/hotel-1/logo", "/dashboard/hotels/hotel-1?logo=saved#logo"),
        (_staff(), "/hotel/details/logo", "/hotel/details?logo=saved#logo"),
    ],
)
def test_a_logo_is_fitted_whole_into_a_square(user: SimpleNamespace, path: str, back: str) -> None:
    client, db = _client(user)
    sent = _upload(client, path)

    assert sent.status_code == 303 and sent.headers["location"] == back
    with Image.open(BytesIO(db.storage.files[LOGO])) as logo:
        assert (logo.format, logo.size) == ("WEBP", (256, 256))
        assert logo.convert("RGB").getpixel((128, 5)) == (255, 255, 255)  # padded, not cropped
        assert logo.convert("RGB").getpixel((128, 128)) != (255, 255, 255)  # the logo itself
    assert db.written("hotels")[0]["logo_version"] > 0


@pytest.mark.parametrize("role", ["content_moderator", "content_creator"])
def test_only_the_hotel_admin_among_staff_sets_it(role: str) -> None:
    client, db = _client(_staff(), role=role)

    assert _upload(client, "/hotel/details/logo").status_code == 403
    assert client.post("/hotel/details/logo/remove").status_code == 403
    assert db.storage.files == {}


def test_a_file_that_isnt_an_image_is_refused() -> None:
    client, db = _client(OPERATOR)
    sent = _upload(client, "/dashboard/hotels/hotel-1/logo", b"not an image")

    assert sent.headers["location"].endswith("?logo=invalid#logo")
    assert db.storage.files == {} and db.written("hotels") == []


def test_removing_deletes_the_object_and_the_version() -> None:
    client, db = _client(OPERATOR, logo_version=5)
    db.storage.files[LOGO] = b"webp"
    sent = client.post("/dashboard/hotels/hotel-1/logo/remove")

    assert sent.headers["location"] == "/dashboard/hotels/hotel-1?logo=removed#logo"
    assert LOGO not in db.storage.files and db.written("hotels") == [{"logo_version": None}]


@pytest.mark.parametrize(
    ("user", "status"), [(OPERATOR, 200), (_staff(), 200), (_staff(user_id="other"), 404)]
)
def test_the_logo_is_shown_to_operators_and_the_hotels_own_staff(
    user: SimpleNamespace, status: int
) -> None:
    client, db = _client(user, logo_version=5)
    db.storage.files[LOGO] = b"webp"

    assert client.get("/logos/hotel-1?v=5").status_code == status


def test_the_pages_show_the_logo_or_the_hotels_initials() -> None:
    client, _ = _client(OPERATOR, logo_version=5)
    assert 'src="/logos/hotel-1?v=5"' in client.get("/dashboard/hotels/hotel-1").text

    client, _ = _client(_staff())
    page = client.get("/hotel/details").text
    assert ">EK</span>" in page and "/logos/" not in page


def test_the_purge_deletes_the_logos_of_deleted_hotels() -> None:
    db = FakeDB(hotel_members=[], hotels=[{"id": "hotel-1"}])
    db.auth = SimpleNamespace(admin=None)  # type: ignore[attr-defined]
    db.storage.files[LOGO] = b"kept"
    db.storage.files[("hotel-assets", "hotel-logos/deleted.webp")] = b"gone"

    profile_photo.purge_orphan_photos(cast(Any, db))
    assert set(db.storage.files) == {LOGO}
