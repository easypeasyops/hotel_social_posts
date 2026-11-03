"""Drafts from Claude: the request the app sends to the Messages API and what it stores.
The HTTP exchange is mocked at the wire (respx), so these tests hold across SDK upgrades."""

import json
from typing import Any

import httpx
import pytest
import respx

from app.config import get_settings
from app.generation.claude import generate_drafts_for_hotel
from app.generation.prompts import SYSTEM_PROMPT, build_generation_prompt
from tests.fakes import FakeDB

MESSAGES_URL = "https://api.anthropic.com/v1/messages"
HOTEL = {
    "id": "hotel-1",
    "name": "Ege Konak",
    "location": "Bodrum",
    "description": "A stone house by the sea.",
    "tier": "standard",
    "channels": ["instagram", "facebook"],
}
ASSETS = [{"id": "asset-1", "filename": "pool.jpg", "category": "pool"}]


def claude_says(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-test",
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10},
        },
    )


POSTS = [
    {"channel": "instagram", "body": "Merhaba #bodrum"},
    {"channel": "facebook", "body": "Hoş geldiniz #ege"},
]


@respx.mock
def test_drafts_are_generated_and_stored_for_review() -> None:
    route = respx.post(MESSAGES_URL).mock(return_value=claude_says(json.dumps(POSTS)))
    db = FakeDB(hotels=[HOTEL], assets=ASSETS)

    ids = generate_drafts_for_hotel(db, "hotel-1")  # type: ignore[arg-type]

    sent: dict[str, Any] = json.loads(route.calls.last.request.content)
    assert route.calls.last.request.headers["x-api-key"] == "test-anthropic-key"
    assert sent["model"] == get_settings().claude_draft_model
    assert sent["system"] == SYSTEM_PROMPT
    assert sent["messages"][0]["content"] == build_generation_prompt(
        HOTEL, ASSETS, ["instagram", "facebook"]
    )
    drafts = db.written("content_drafts")
    assert [d["id"] for d in drafts] == ids
    assert [(d["channel"], d["body_tr"]) for d in drafts] == [
        ("instagram", "Merhaba #bodrum"),
        ("facebook", "Hoş geldiniz #ege"),
    ]
    assert all(d["status"] == "pending_review" and d["asset_ids"] == ["asset-1"] for d in drafts)


@respx.mock
def test_prose_around_the_json_is_ignored() -> None:
    reply = f"Here are your posts:\n{json.dumps(POSTS[:1])}\nEnjoy!"
    respx.post(MESSAGES_URL).mock(return_value=claude_says(reply))
    db = FakeDB(hotels=[HOTEL], assets=[])

    generate_drafts_for_hotel(db, "hotel-1")  # type: ignore[arg-type]

    assert [d["body_tr"] for d in db.written("content_drafts")] == ["Merhaba #bodrum"]


@pytest.mark.parametrize("tier", ["growth", "premium"])
@respx.mock
def test_paid_tiers_get_the_premium_model(tier: str) -> None:
    route = respx.post(MESSAGES_URL).mock(return_value=claude_says("[]"))
    generate_drafts_for_hotel(FakeDB(hotels=[{**HOTEL, "tier": tier}]), "hotel-1")  # type: ignore[arg-type]

    assert json.loads(route.calls.last.request.content)["model"] == (
        get_settings().claude_premium_model
    )


@respx.mock
def test_an_unknown_hotel_calls_nobody() -> None:
    route = respx.post(MESSAGES_URL)
    with pytest.raises(ValueError, match="not found"):
        generate_drafts_for_hotel(FakeDB(), "missing")  # type: ignore[arg-type]
    assert not route.called


def test_the_prompt_names_the_hotel_and_its_assets() -> None:
    prompt = build_generation_prompt(HOTEL, ASSETS, ["instagram"])
    assert "Ege Konak" in prompt and "Bodrum" in prompt
    assert "Pool: pool.jpg (ID: asset-1)" in prompt
    assert "Write exactly 1 post(s)" in prompt
    no_assets = build_generation_prompt({**HOTEL, "description": None}, [], ["instagram"])
    assert "No assets uploaded yet" in no_assets
    assert "A beautiful hotel in Türkiye." in no_assets
