"""Translations from DeepL: one request per language the hotel's tier includes; a language
that fails is skipped, the others are stored."""

import asyncio
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from app.translation.deepl import DEEPL_API_URL, translate_draft
from tests.fakes import FakeDB


def draft(tier: str) -> dict[str, object]:
    return {"id": "draft-1", "body_tr": "Merhaba", "hotels": {"tier": tier}}


def deepl(request: httpx.Request) -> httpx.Response:
    form = parse_qs(request.content.decode())
    if form["target_lang"] == ["RU"]:
        return httpx.Response(503)
    return httpx.Response(
        200, json={"translations": [{"text": f"{form['target_lang'][0]}: {form['text'][0]}"}]}
    )


@respx.mock
def test_each_language_of_the_tier_is_requested_and_stored() -> None:
    route = respx.post(DEEPL_API_URL).mock(side_effect=deepl)
    db = FakeDB(content_drafts=[draft("standard")])

    asyncio.run(translate_draft(db, "draft-1"))  # type: ignore[arg-type]

    form = parse_qs(route.calls.last.request.content.decode())
    assert form["auth_key"] == ["test-deepl-key"]
    assert form["source_lang"] == ["TR"]
    assert db.written("content_translations") == [
        {"draft_id": "draft-1", "language": "en", "body": "EN: Merhaba"}
    ]


@respx.mock
def test_a_failed_language_does_not_block_the_others() -> None:
    respx.post(DEEPL_API_URL).mock(side_effect=deepl)
    db = FakeDB(content_drafts=[draft("growth")])

    asyncio.run(translate_draft(db, "draft-1"))  # type: ignore[arg-type]

    stored = {row["language"]: row["body"] for row in db.written("content_translations")}
    assert stored == {"en": "EN: Merhaba", "de": "DE: Merhaba", "ar": "AR: Merhaba"}


@respx.mock
def test_an_unknown_draft_calls_nobody() -> None:
    route = respx.post(DEEPL_API_URL)
    with pytest.raises(ValueError, match="not found"):
        asyncio.run(translate_draft(FakeDB(), "missing"))  # type: ignore[arg-type]
    assert not route.called
