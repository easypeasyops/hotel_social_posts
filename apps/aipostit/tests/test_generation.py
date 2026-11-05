"""Drafts from Claude: the request the app sends to the Messages API and what it stores.
The HTTP exchange is mocked at the wire: anthropic 2.x makes its calls with httpx2, so the
client gets an httpx2 MockTransport (respx only intercepts httpx). These tests check the
request itself, so they hold across SDK upgrades."""

import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import pytest

from app.config import get_settings
from app.generation import claude
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


def claude_says(text: str) -> httpx2.Response:
    return httpx2.Response(
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


Calls = list[httpx2.Request]


@pytest.fixture
def claude_replies(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], Calls]:
    """Make Claude answer with `text`; returns the list the requests sent to it land in."""

    def reply_with(text: str) -> Calls:
        calls: Calls = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            calls.append(request)
            return claude_says(text)

        transport = httpx2.MockTransport(handler)
        monkeypatch.setattr(
            claude,
            "_client",
            lambda key: anthropic.Anthropic(
                api_key=key, http_client=httpx2.Client(transport=transport)
            ),
        )
        return calls

    return reply_with


POSTS = [
    {"channel": "instagram", "body": "Merhaba #bodrum"},
    {"channel": "facebook", "body": "Hoş geldiniz #ege"},
]


def test_drafts_are_generated_and_stored_for_review(
    claude_replies: Callable[[str], Calls],
) -> None:
    calls = claude_replies(json.dumps(POSTS))
    db = FakeDB(hotels=[HOTEL], assets=ASSETS)

    ids = generate_drafts_for_hotel(db, "hotel-1")  # type: ignore[arg-type]

    (request,) = calls
    sent: dict[str, Any] = json.loads(request.content)
    assert str(request.url) == MESSAGES_URL
    # anthropic 2.x sends the API key as a bearer token (0.x used x-api-key).
    assert request.headers["authorization"] == "Bearer test-anthropic-key"
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


def test_prose_around_the_json_is_ignored(claude_replies: Callable[[str], Calls]) -> None:
    claude_replies(f"Here are your posts:\n{json.dumps(POSTS[:1])}\nEnjoy!")
    db = FakeDB(hotels=[HOTEL], assets=[])

    generate_drafts_for_hotel(db, "hotel-1")  # type: ignore[arg-type]

    assert [d["body_tr"] for d in db.written("content_drafts")] == ["Merhaba #bodrum"]


@pytest.mark.parametrize("tier", ["growth", "premium"])
def test_paid_tiers_get_the_premium_model(
    claude_replies: Callable[[str], Calls], tier: str
) -> None:
    calls = claude_replies("[]")
    generate_drafts_for_hotel(FakeDB(hotels=[{**HOTEL, "tier": tier}]), "hotel-1")  # type: ignore[arg-type]

    assert json.loads(calls[0].content)["model"] == get_settings().claude_premium_model


def test_an_unknown_hotel_calls_nobody(claude_replies: Callable[[str], Calls]) -> None:
    calls = claude_replies("[]")
    with pytest.raises(ValueError, match="not found"):
        generate_drafts_for_hotel(FakeDB(), "missing")  # type: ignore[arg-type]
    assert calls == []


def test_the_prompt_names_the_hotel_and_its_assets() -> None:
    prompt = build_generation_prompt(HOTEL, ASSETS, ["instagram"])
    assert "Ege Konak" in prompt and "Bodrum" in prompt
    assert "Pool: pool.jpg (ID: asset-1)" in prompt
    assert "Write exactly 1 post(s)" in prompt
    no_assets = build_generation_prompt({**HOTEL, "description": None}, [], ["instagram"])
    assert "No assets uploaded yet" in no_assets
    assert "A beautiful hotel in Türkiye." in no_assets
