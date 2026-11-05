"""A draft's post preview on the review pages: the images the post will carry (as publishing
picks them), through short-lived signed links to the private bucket, with the text, in the
look of the draft's network."""

from typing import Any

import pytest

from app.assets.service import STORAGE_BUCKET
from app.content.preview import PREVIEW_LINK_SECONDS, preview_images, review_images
from tests.fakes import FakeDB


def _asset(asset_id: str, filename: str, status: str = "ready") -> dict[str, Any]:
    return {"id": asset_id, "filename": filename, "status": status,
            "storage_path": f"hotel-1/{asset_id}/{filename}"}  # fmt: skip


ASSETS = [
    _asset("pool", "pool.jpg"),
    _asset("room", "room.PNG"),
    _asset("drone", "drone.mp4"),  # a video: not posted yet
    _asset("lobby", "lobby.jpg", status="pending"),  # not uploaded yet
]


def _signed(asset: dict[str, Any]) -> str:
    return f"https://supabase.invalid/storage/v1/object/sign/{STORAGE_BUCKET}/{asset['storage_path']}?token=t"


def test_each_draft_gets_signed_links_to_the_images_its_post_will_carry() -> None:
    db = FakeDB()
    drafts = [
        {"id": "d1", "asset_ids": ["room", "drone", "lobby", "pool", "gone"]},
        {"id": "d2", "asset_ids": []},
        {"id": "d3"},
    ]

    images = preview_images(db, ASSETS, drafts)  # type: ignore[arg-type]

    assert images == {"d1": [_signed(ASSETS[1]), _signed(ASSETS[0])], "d2": [], "d3": []}
    # One request for the page, links that outlive a review but not much more.
    assert db.storage.signed == [
        (STORAGE_BUCKET, ["hotel-1/pool/pool.jpg", "hotel-1/room/room.PNG"], PREVIEW_LINK_SECONDS)
    ]


def test_no_images_means_no_request_to_storage() -> None:
    db = FakeDB()
    assert preview_images(db, ASSETS, [{"id": "d1", "asset_ids": ["drone"]}]) == {"d1": []}  # type: ignore[arg-type]
    assert db.storage.signed == []


def test_storage_failing_leaves_the_text_to_review(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    db = FakeDB()

    def down(*_: Any) -> list[dict[str, Any]]:
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr("tests.fakes.FakeBucket.create_signed_urls", down)
    assert preview_images(db, ASSETS, [{"id": "d1", "asset_ids": ["pool"]}]) == {"d1": []}  # type: ignore[arg-type]
    assert "storage unavailable" in caplog.text


def _render(channel: str, images: list[str]) -> str:
    from app.main import templates

    return templates.get_template("preview/post.html").render(
        draft={"channel": channel, "body_tr": "Merhaba"},
        hotel={"name": "Ege Konak", "slug": "ege-konak"},
        images=images,
    )


@pytest.mark.parametrize(
    ("count", "shown", "more"), [(1, 1, None), (2, 2, None), (3, 3, None), (5, 4, "+1")]
)
def test_facebook_shows_the_text_then_up_to_four_images(
    count: int, shown: int, more: str | None
) -> None:
    page = _render("facebook", [f"https://img.invalid/{n}.jpg" for n in range(count)])
    assert 'data-preview="facebook"' in page
    assert page.index("Merhaba") < page.index("<img")  # the text above the images, as on Facebook
    assert page.count("<img") == shown
    assert (more in page) if more else ("+" not in page.split("<img", 1)[1])


def test_every_network_has_its_own_look() -> None:
    from app.hotels.models import SocialChannel

    for channel in SocialChannel:
        assert f'data-preview="{channel.value}"' in _render(channel.value, [])


def test_tiktok_shows_every_image_in_a_vertical_frame() -> None:
    page = _render("tiktok", [f"https://img.invalid/{n}.jpg" for n in range(3)])
    assert page.count("<img") == 3
    assert "aspect-[9/16]" in page and "@egekonak" in page and "Merhaba" in page


def test_google_business_shows_the_first_image_only() -> None:
    page = _render("google_business", ["https://img.invalid/1.jpg", "https://img.invalid/2.jpg"])
    assert page.count("<img") == 1 and "1.jpg" in page
    assert page.index("<img") < page.index("Merhaba")


def test_the_photo_picker_shows_thumbnails_and_the_preview_the_photo() -> None:
    db = FakeDB()
    pool = {**ASSETS[0], "thumbnail_path": "thumbnails/hotel-1/pool.webp"}
    assets = [pool, *ASSETS[1:]]

    previews, thumbnails = review_images(db, assets, [{"id": "d1", "asset_ids": ["pool"]}])  # type: ignore[arg-type]

    assert previews == {"d1": [_signed(pool)]}
    assert thumbnails == {
        "pool": _signed({"storage_path": "thumbnails/hotel-1/pool.webp"}),
        "room": _signed(ASSETS[1]),  # no thumbnail yet: the photo itself
    }
    assert len(db.storage.signed) == 1
