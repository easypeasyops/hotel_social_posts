"""Publishing to Buffer's GraphQL API: an approved draft goes to the top of the queue of the
hotel's channel for its network, and the Buffer post is logged. Buffer answers HTTP 200 even
when it refuses: errors are in the body."""

import json
from typing import Any

import httpx
import pytest
import respx

from app.assets.service import STORAGE_BUCKET
from app.publishing.buffer import (
    BUFFER_API_URL,
    MAX_IMAGES,
    PUBLISHED_BUCKET,
    BufferError,
    publish_draft,
)
from tests.fakes import FakeDB

HOTEL = {
    "id": "hotel-1",
    "buffer_profiles": {"instagram": "channel-ig", "facebook": "channel-fb"},
}
POOL = {"id": "asset-1", "filename": "Pool.JPG", "storage_path": "hotel-1/asset-1/Pool.JPG"}
VIDEO = {"id": "asset-2", "filename": "drone.mp4", "storage_path": "hotel-1/asset-2/drone.mp4"}


def draft(channel: str = "instagram", asset_ids: list[str] | None = None) -> dict[str, object]:
    return {
        "id": "draft-1",
        "channel": channel,
        "body_tr": "Merhaba",
        "hotels": HOTEL,
        "asset_ids": ["asset-1"] if asset_ids is None else asset_ids,
    }


def db_with(*assets: dict[str, str], **draft_args: object) -> FakeDB:
    db = FakeDB(content_drafts=[draft(**draft_args)], assets=list(assets))  # type: ignore[arg-type]
    for asset in assets:
        db.storage.files[(STORAGE_BUCKET, asset["storage_path"])] = asset["id"].encode()
    return db


def buffer_says(body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=body)


@respx.mock
def test_a_draft_goes_to_the_top_of_its_channels_queue_and_is_logged() -> None:
    route = respx.post(BUFFER_API_URL).mock(
        return_value=buffer_says({"data": {"createPost": {"post": {"id": "post-1"}}}})
    )
    db = db_with(POOL)

    publish_draft(db, "draft-1")  # type: ignore[arg-type]

    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer test-buffer-token"
    sent = json.loads(request.content)
    assert "createPost(input: $input)" in sent["query"]
    assert "... on MutationError" in sent["query"]
    assert sent["variables"] == {
        "input": {
            "channelId": "channel-ig",
            "text": "Merhaba",
            "schedulingType": "automatic",
            "mode": "shareNext",
            # Buffer refuses an Instagram post without its type (seen 2026-11-04).
            "metadata": {"instagram": {"type": "post", "shouldShareToFeed": True}},
            "assets": [
                {
                    "image": {
                        "url": "https://supabase.invalid/storage/v1/object/public/"
                        "published-media/hotel-1/draft-1/asset-1.jpg"
                    }
                }
            ],
        }
    }
    # Copied from the private upload bucket into the public one, overwriting on a retry.
    assert db.storage.files[(PUBLISHED_BUCKET, "hotel-1/draft-1/asset-1.jpg")] == b"asset-1"
    assert db.storage.uploads[0][2] == {"content-type": "image/jpeg", "upsert": "true"}
    assert db.written("publish_log") == [
        {
            "draft_id": "draft-1",
            "hotel_id": "hotel-1",
            "channel": "instagram",
            "buffer_update_id": "post-1",
            "status": "scheduled",
        }
    ]


@respx.mock
def test_a_channel_without_a_buffer_channel_is_not_sent() -> None:
    route = respx.post(BUFFER_API_URL)
    with pytest.raises(ValueError, match="No Buffer channel"):
        publish_draft(db_with(POOL, channel="linkedin"), "draft-1")  # type: ignore[arg-type]
    assert not route.called


@respx.mock
def test_instagram_without_an_image_is_not_sent() -> None:
    # Instagram refuses text-only posts; a video isn't sent yet, so it doesn't count.
    route = respx.post(BUFFER_API_URL)
    db = db_with(VIDEO, asset_ids=["asset-2"])
    with pytest.raises(ValueError, match="no ready image"):
        publish_draft(db, "draft-1")  # type: ignore[arg-type]
    assert not route.called
    assert db.storage.uploads == []


@respx.mock
def test_facebook_without_an_image_posts_the_text() -> None:
    route = respx.post(BUFFER_API_URL).mock(
        return_value=buffer_says({"data": {"createPost": {"post": {"id": "post-2"}}}})
    )
    publish_draft(db_with(channel="facebook", asset_ids=[]), "draft-1")  # type: ignore[arg-type]
    sent = json.loads(route.calls.last.request.content)["variables"]["input"]
    assert "assets" not in sent
    assert "metadata" not in sent  # Buffer requires no settings for a Facebook post


@respx.mock
def test_images_keep_the_drafts_order_and_stop_at_instagrams_limit() -> None:
    route = respx.post(BUFFER_API_URL).mock(
        return_value=buffer_says({"data": {"createPost": {"post": {"id": "post-3"}}}})
    )
    images = [
        {"id": f"img-{n:02}", "filename": f"{n}.png", "storage_path": f"hotel-1/img-{n:02}"}
        for n in range(MAX_IMAGES + 2)
    ]
    ids = [image["id"] for image in reversed(images)]
    publish_draft(db_with(*images, VIDEO, asset_ids=["asset-2", *ids]), "draft-1")  # type: ignore[arg-type]

    sent = json.loads(route.calls.last.request.content)["variables"]["input"]["assets"]
    assert [a["image"]["url"].rsplit("/", 1)[1] for a in sent] == [
        f"{asset_id}.png" for asset_id in ids[:MAX_IMAGES]
    ]


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"data": {"createPost": {"message": "Queue limit reached"}}}, "Queue limit reached"),
        (
            {
                "data": None,
                # What Buffer answers a key it doesn't accept (seen 2026-11-03).
                "errors": [
                    {
                        "message": "Access token is not valid",
                        "extensions": {"code": "UNAUTHENTICATED"},
                    }
                ],
            },
            "UNAUTHENTICATED: Access token is not valid",
        ),
    ],
)
@respx.mock
def test_a_refused_post_raises_and_is_not_logged(body: dict[str, Any], error: str) -> None:
    respx.post(BUFFER_API_URL).mock(return_value=buffer_says(body))
    db = db_with(POOL)
    with pytest.raises(BufferError, match=error):
        publish_draft(db, "draft-1")  # type: ignore[arg-type]
    assert db.written("publish_log") == []


@respx.mock
def test_the_rate_limit_raises_so_the_task_retries() -> None:
    respx.post(BUFFER_API_URL).mock(return_value=httpx.Response(429))
    db = db_with(POOL)
    with pytest.raises(httpx.HTTPStatusError):
        publish_draft(db, "draft-1")  # type: ignore[arg-type]
    assert db.written("publish_log") == []
