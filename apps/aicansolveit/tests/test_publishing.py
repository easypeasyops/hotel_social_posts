"""Publishing to Buffer's GraphQL API: an approved draft goes to the top of the queue of the
hotel's channel for its network, and the Buffer post is logged. Buffer answers HTTP 200 even
when it refuses: errors are in the body."""

import json
from typing import Any

import httpx
import pytest
import respx

from app.publishing.buffer import BUFFER_API_URL, BufferError, publish_draft
from tests.fakes import FakeDB

HOTEL = {"id": "hotel-1", "buffer_profiles": {"instagram": "channel-ig"}}


def draft(channel: str = "instagram") -> dict[str, object]:
    return {"id": "draft-1", "channel": channel, "body_tr": "Merhaba", "hotels": HOTEL}


def buffer_says(body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=body)


@respx.mock
def test_a_draft_goes_to_the_top_of_its_channels_queue_and_is_logged() -> None:
    route = respx.post(BUFFER_API_URL).mock(
        return_value=buffer_says({"data": {"createPost": {"post": {"id": "post-1"}}}})
    )
    db = FakeDB(content_drafts=[draft()])

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
        }
    }
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
        publish_draft(FakeDB(content_drafts=[draft("facebook")]), "draft-1")  # type: ignore[arg-type]
    assert not route.called


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({"data": {"createPost": {"message": "Queue limit reached"}}}, "Queue limit reached"),
        (
            {
                "data": None,
                "errors": [{"message": "Not authorized", "extensions": {"code": "UNAUTHORIZED"}}],
            },
            "UNAUTHORIZED: Not authorized",
        ),
    ],
)
@respx.mock
def test_a_refused_post_raises_and_is_not_logged(body: dict[str, Any], error: str) -> None:
    respx.post(BUFFER_API_URL).mock(return_value=buffer_says(body))
    db = FakeDB(content_drafts=[draft()])
    with pytest.raises(BufferError, match=error):
        publish_draft(db, "draft-1")  # type: ignore[arg-type]
    assert db.written("publish_log") == []


@respx.mock
def test_the_rate_limit_raises_so_the_task_retries() -> None:
    respx.post(BUFFER_API_URL).mock(return_value=httpx.Response(429))
    db = FakeDB(content_drafts=[draft()])
    with pytest.raises(httpx.HTTPStatusError):
        publish_draft(db, "draft-1")  # type: ignore[arg-type]
    assert db.written("publish_log") == []
