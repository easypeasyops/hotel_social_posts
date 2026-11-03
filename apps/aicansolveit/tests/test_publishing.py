"""Publishing to Buffer: an approved draft goes to the hotel's profile for its channel and
the Buffer update is logged."""

from urllib.parse import parse_qs

import httpx
import pytest
import respx

from app.publishing.buffer import BUFFER_API_URL, publish_draft
from tests.fakes import FakeDB

CREATE_URL = f"{BUFFER_API_URL}/updates/create.json"
HOTEL = {"id": "hotel-1", "buffer_profiles": {"instagram": "profile-ig"}}


def draft(channel: str = "instagram") -> dict[str, object]:
    return {"id": "draft-1", "channel": channel, "body_tr": "Merhaba", "hotels": HOTEL}


@respx.mock
def test_a_draft_is_queued_on_its_channel_and_logged() -> None:
    route = respx.post(CREATE_URL).mock(
        return_value=httpx.Response(200, json={"success": True, "updates": [{"id": "upd-1"}]})
    )
    db = FakeDB(content_drafts=[draft()])

    publish_draft(db, "draft-1")  # type: ignore[arg-type]

    form = parse_qs(route.calls.last.request.content.decode())
    assert form["profile_ids[]"] == ["profile-ig"]
    assert form["text"] == ["Merhaba"]
    assert form["access_token"] == ["test-buffer-token"]
    assert db.written("publish_log") == [
        {
            "draft_id": "draft-1",
            "hotel_id": "hotel-1",
            "channel": "instagram",
            "buffer_update_id": "upd-1",
            "status": "scheduled",
        }
    ]


@respx.mock
def test_a_channel_without_a_profile_is_not_sent() -> None:
    route = respx.post(CREATE_URL)
    with pytest.raises(ValueError, match="No Buffer profile"):
        publish_draft(FakeDB(content_drafts=[draft("facebook")]), "draft-1")  # type: ignore[arg-type]
    assert not route.called


@respx.mock
def test_a_refused_post_is_not_logged() -> None:
    respx.post(CREATE_URL).mock(return_value=httpx.Response(400, json={"success": False}))
    db = FakeDB(content_drafts=[draft()])
    with pytest.raises(httpx.HTTPStatusError):
        publish_draft(db, "draft-1")  # type: ignore[arg-type]
    assert db.written("publish_log") == []
