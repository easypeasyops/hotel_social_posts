import httpx
from supabase import Client
from app.config import get_settings

BUFFER_API_URL = "https://api.bufferapp.com/1"


def _get_profile_id(channel: str, hotel: dict) -> str | None:
    """
    Returns the Buffer profile ID for a given channel stored on the hotel record.
    Expected hotel schema: buffer_profiles = {"instagram": "profile_id", ...}
    """
    profiles = hotel.get("buffer_profiles") or {}
    return profiles.get(channel)


def publish_draft(db: Client, draft_id: str) -> None:
    """
    Submits an approved draft to Buffer for scheduling.
    Uses the Turkish body as the primary text (Buffer handles one language per post).
    For multilingual publishing, separate posts per language would be needed — deferred to v2.
    """
    settings = get_settings()

    draft = db.table("content_drafts").select("*, hotels(*)").eq("id", draft_id).single().execute().data
    if not draft:
        raise ValueError(f"Draft {draft_id} not found")

    hotel = draft["hotels"]
    channel = draft["channel"]
    profile_id = _get_profile_id(channel, hotel)

    if not profile_id:
        raise ValueError(f"No Buffer profile configured for channel '{channel}' on hotel '{hotel['id']}'")

    payload = {
        "profile_ids[]": profile_id,
        "text": draft["body_tr"],
        "now": False,          # let Buffer schedule it at the optimal time
        "top": True,           # add to top of queue
        "access_token": settings.buffer_access_token,
    }

    with httpx.Client(timeout=15) as client:
        response = client.post(f"{BUFFER_API_URL}/updates/create.json", data=payload)
        response.raise_for_status()

    result = response.json()

    # Record the Buffer update ID for webhook correlation
    db.table("publish_log").insert({
        "draft_id": draft_id,
        "hotel_id": hotel["id"],
        "channel": channel,
        "buffer_update_id": result.get("updates", [{}])[0].get("id"),
        "status": "scheduled",
    }).execute()
