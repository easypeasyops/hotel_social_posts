import asyncio

import httpx

from app.config import get_settings
from supabase import Client

# Languages enabled per subscription tier
TIER_LANGUAGES = {
    "standard": ["en"],  # TR is the source; EN is translated
    "growth": ["en", "de", "ru", "ar"],
    "premium": ["en", "de", "ru", "ar"],
}

DEEPL_API_URL = "https://api-free.deepl.com/v2/translate"  # free tier endpoint


async def _translate_text(
    client: httpx.AsyncClient, text: str, target_lang: str, api_key: str
) -> str:
    # The key goes in the Authorization header: DeepL refuses `auth_key` in the body or the
    # query (403) since 2026-01-15.
    response = await client.post(
        DEEPL_API_URL,
        headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
        data={
            "text": text,
            "source_lang": "TR",
            "target_lang": target_lang.upper(),
        },
    )
    response.raise_for_status()
    return response.json()["translations"][0]["text"]


async def translate_draft(db: Client, draft_id: str) -> None:
    """
    Translates a draft into all languages for the hotel's tier.
    Runs all language calls concurrently.
    """
    settings = get_settings()

    draft = (
        db.table("content_drafts")
        .select("*, hotels(tier)")
        .eq("id", draft_id)
        .single()
        .execute()
        .data
    )
    if not draft:
        raise ValueError(f"Draft {draft_id} not found")

    tier = draft.get("hotels", {}).get("tier", "standard")
    target_languages = TIER_LANGUAGES.get(tier, ["en"])
    source_text = draft["body_tr"]

    async with httpx.AsyncClient(timeout=30) as client:
        tasks = {
            lang: _translate_text(client, source_text, lang, settings.deepl_api_key)
            for lang in target_languages
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    translations = dict(zip(tasks.keys(), results))  # noqa: B905

    # Persist translations
    for lang, result in translations.items():
        if isinstance(result, Exception):
            # Log and skip failed translations — don't block the whole draft
            print(f"Translation failed for {draft_id} → {lang}: {result}")
            continue

        db.table("content_translations").upsert(
            {
                "draft_id": draft_id,
                "language": lang,
                "body": result,
            },
            on_conflict="draft_id,language",
        ).execute()
