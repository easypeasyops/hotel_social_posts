import json
import uuid

import anthropic

from app.config import get_settings
from app.generation.prompts import SYSTEM_PROMPT, build_generation_prompt
from supabase import Client


def generate_drafts_for_hotel(db: Client, hotel_id: str) -> list[str]:
    """
    Generates content drafts for a hotel using Claude API.
    Returns a list of created draft IDs.
    """
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # Load hotel profile
    hotel = db.table("hotels").select("*").eq("id", hotel_id).single().execute().data
    if not hotel:
        raise ValueError(f"Hotel {hotel_id} not found")

    # Load ready assets (most recent 10)
    assets = (
        db.table("assets")
        .select("id, filename, category")
        .eq("hotel_id", hotel_id)
        .eq("status", "ready")
        .order("created_at", desc=True)
        .limit(10)
        .execute()
        .data
    )

    channels = hotel.get("channels", ["instagram"])
    prompt = build_generation_prompt(hotel, assets, channels)

    # Choose model based on tier
    model = (
        settings.claude_premium_model
        if hotel.get("tier") in ("growth", "premium")
        else settings.claude_draft_model
    )

    message = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    try:
        posts = json.loads(raw)
    except json.JSONDecodeError:
        # Retry with explicit instruction if Claude added prose around the JSON
        start = raw.find("[")
        end = raw.rfind("]") + 1
        posts = json.loads(raw[start:end])

    # Persist drafts
    draft_ids = []
    for post in posts:
        draft_id = str(uuid.uuid4())
        db.table("content_drafts").insert(
            {
                "id": draft_id,
                "hotel_id": hotel_id,
                "channel": post.get("channel", "instagram"),
                "body_tr": post["body"],
                "asset_ids": [a["id"] for a in assets],
                "status": "pending_review",
            }
        ).execute()
        draft_ids.append(draft_id)

    return draft_ids
