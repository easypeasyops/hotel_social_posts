import logging
from pathlib import PurePosixPath
from typing import Any

import httpx

from app.assets.service import STORAGE_BUCKET
from app.config import get_settings
from supabase import Client

# Buffer's GraphQL API. The legacy REST API (api.bufferapp.com/1) has brownouts from
# 2026-11-11 and stops on 2027-02-01: https://buffer.com/resources/legacy-rest-api-retired/
BUFFER_API_URL = "https://api.buffer.com"

# One post per channel. shareNext puts it at the top of the channel's queue, as the REST
# call's top=true did. MutationError is the catch-all for every typed error Buffer returns.
CREATE_POST = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id } }
    ... on MutationError { message }
  }
}
"""

# A post's place in its lifecycle (PostStatus: draft, needs_approval, scheduled, sending, sent,
# error), when it went out, and why it didn't.
GET_POST = """
query Post($input: PostInput!) {
  post(input: $input) { status sentAt error { message } }
}
"""

log = logging.getLogger(__name__)


# Buffer fetches a post's media when the post goes out, which for a queued post can be days
# later, so the URL must not expire (Buffer warns against signed URLs). Images being posted
# are copied from the private upload bucket into this public one
# (supabase/migrations/002_published_media_bucket.sql). They're public on the network anyway.
PUBLISHED_BUCKET = "published-media"
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
MAX_IMAGES = 10  # Instagram's carousel limit
NEEDS_IMAGE = {"instagram"}  # Instagram refuses text-only posts

# What Buffer requires per network (CreatePostInput.metadata). Instagram: the kind of post
# and whether it shows in the feed. Without it Buffer refuses the post ("Instagram posts
# require a type (post, story, or reel)"). Ours are feed posts of photos; reels and stories
# would need vertical video.
METADATA: dict[str, dict[str, Any]] = {
    "instagram": {"instagram": {"type": "post", "shouldShareToFeed": True}},
}


class BufferError(RuntimeError):
    """Buffer refused the post. GraphQL answers HTTP 200 either way: the error is in the body."""


def _get_channel_id(channel: str, hotel: dict[str, Any]) -> str | None:
    """
    Returns the Buffer channel ID for a given channel stored on the hotel record.
    Expected hotel schema: buffer_profiles = {"instagram": "channel_id", ...}
    (Buffer's REST API called channels profiles; the column keeps that name.)
    """
    profiles = hotel.get("buffer_profiles") or {}
    channel_id: str | None = profiles.get(channel)
    return channel_id


def _publish_images(db: Client, hotel_id: str, draft_id: str, asset_ids: list[str]) -> list[str]:
    """Public URLs for the draft's images, in the draft's order, at most MAX_IMAGES.
    Videos and other files are skipped: posts carry images only, for now."""
    if not asset_ids:
        return []
    rows = (
        db.table("assets")
        .select("id, filename, storage_path")
        .in_("id", asset_ids)
        .eq("status", "ready")
        .execute()
        .data
    )
    by_id = {row["id"]: row for row in rows}
    urls: list[str] = []
    for asset_id in asset_ids:
        asset = by_id.get(asset_id)
        suffix = PurePosixPath(asset["filename"]).suffix.lower() if asset else ""
        if not asset or suffix not in IMAGE_TYPES:
            continue
        data = db.storage.from_(STORAGE_BUCKET).download(asset["storage_path"])
        path = f"{hotel_id}/{draft_id}/{asset_id}{suffix}"
        published = db.storage.from_(PUBLISHED_BUCKET)
        # upsert: a retried task writes the same path again
        published.upload(path, data, {"content-type": IMAGE_TYPES[suffix], "upsert": "true"})
        urls.append(published.get_public_url(path))
        if len(urls) == MAX_IMAGES:
            break
    return urls


def _create_post(
    channel_id: str, text: str, api_key: str, image_urls: list[str], channel: str
) -> str:
    post_input: dict[str, Any] = {
        "channelId": channel_id,
        "text": text,
        "schedulingType": "automatic",
        "mode": "shareNext",
    }
    if channel in METADATA:
        post_input["metadata"] = METADATA[channel]
    if image_urls:
        post_input["assets"] = [{"image": {"url": url}} for url in image_urls]
    variables = {"input": post_input}
    with httpx.Client(timeout=15) as client:
        response = client.post(
            BUFFER_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"query": CREATE_POST, "variables": variables},
        )
        response.raise_for_status()  # 429 when the rate limit is exceeded
    body = response.json()
    if body.get("errors"):  # auth, permissions, not found, server: not fixable by input
        error = body["errors"][0]
        code = (error.get("extensions") or {}).get("code", "UNKNOWN")
        raise BufferError(f"{code}: {error.get('message')}")
    result = (body.get("data") or {}).get("createPost") or {}
    post = result.get("post")
    if not post:  # a typed MutationError: invalid input, limit reached, ...
        raise BufferError(result.get("message") or "Buffer did not create the post")
    post_id: str = post["id"]
    return post_id


def publish_draft(db: Client, draft_id: str) -> None:
    """
    Submits an approved draft to Buffer for scheduling.
    Uses the Turkish body as the primary text (Buffer handles one language per post).
    For multilingual publishing, separate posts per language would be needed — deferred to v2.
    """
    settings = get_settings()

    draft = (
        db.table("content_drafts").select("*, hotels(*)").eq("id", draft_id).single().execute().data
    )
    if not draft:
        raise ValueError(f"Draft {draft_id} not found")

    hotel = draft["hotels"]
    channel = draft["channel"]
    channel_id = _get_channel_id(channel, hotel)

    if not channel_id:
        raise ValueError(
            f"No Buffer channel configured for channel '{channel}' on hotel '{hotel['id']}'"
        )

    image_urls = _publish_images(db, hotel["id"], draft_id, draft.get("asset_ids") or [])
    if channel in NEEDS_IMAGE and not image_urls:
        raise ValueError(
            f"Draft {draft_id} has no ready image, and {channel} refuses text-only posts"
        )

    post_id = _create_post(
        channel_id, draft["body_tr"], settings.buffer_access_token, image_urls, channel
    )

    # Record the Buffer post ID for correlation
    db.table("publish_log").insert(
        {
            "draft_id": draft_id,
            "hotel_id": hotel["id"],
            "channel": channel,
            "buffer_update_id": post_id,
            "status": "scheduled",
        }
    ).execute()


def _get_post(post_id: str, api_key: str) -> dict[str, Any]:
    with httpx.Client(timeout=15) as client:
        response = client.post(
            BUFFER_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"query": GET_POST, "variables": {"input": {"id": post_id}}},
        )
        response.raise_for_status()  # 429 when the rate limit is exceeded
    body = response.json()
    if body.get("errors"):  # not found (deleted in Buffer's app), auth, ...
        error = body["errors"][0]
        code = (error.get("extensions") or {}).get("code", "UNKNOWN")
        raise BufferError(f"{code}: {error.get('message')}")
    post: dict[str, Any] = body["data"]["post"]
    return post


def sync_scheduled_posts(db: Client) -> None:
    """
    Brings Buffer's outcome back for every post still logged as scheduled: Buffer sent it
    (publish log and draft `published`, with when) or couldn't (both `failed`). A post still
    queued is left for the next run. A post Buffer won't show is logged and skipped, so one
    deleted post doesn't stop the others; the rate limit stops the run.
    """
    api_key = get_settings().buffer_access_token
    scheduled = (
        db.table("publish_log")
        .select("id, draft_id, buffer_update_id")
        .eq("status", "scheduled")
        .execute()
        .data
    )
    for entry in scheduled:
        try:
            post = _get_post(entry["buffer_update_id"], api_key)
        except BufferError as exc:
            log.warning("Buffer post %s: %s", entry["buffer_update_id"], exc)
            continue
        if post["status"] == "sent":
            outcome = {"status": "published", "published_at": post["sentAt"]}
        elif post["status"] == "error":
            outcome = {"status": "failed"}
            message = (post.get("error") or {}).get("message")
            log.warning("Buffer couldn't send post %s: %s", entry["buffer_update_id"], message)
        else:
            continue
        db.table("publish_log").update(outcome).eq("id", entry["id"]).execute()
        db.table("content_drafts").update({"status": outcome["status"]}).eq(
            "id", entry["draft_id"]
        ).execute()
