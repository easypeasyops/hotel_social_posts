"""What a draft's post preview shows: the images publishing will send (postable_images),
through signed links, since `hotel-assets` is private."""

import logging
from typing import Any

from app.assets.service import STORAGE_BUCKET
from app.publishing.buffer import postable_images
from supabase import Client

log = logging.getLogger(__name__)

# Long enough to review a page of drafts, short enough not to be a lasting link to the files.
PREVIEW_LINK_SECONDS = 3600


def preview_images(
    db: Client, assets: list[dict[str, Any]], drafts: list[dict[str, Any]]
) -> dict[str, list[str]]:
    """Each draft's postable images as signed links, in the draft's order, from the hotel's
    `assets`; one Storage request for them all. If Storage fails, no images: the text can
    still be reviewed."""
    ready = [asset for asset in assets if asset.get("status") == "ready"]
    chosen = {d["id"]: postable_images(ready, d.get("asset_ids") or []) for d in drafts}
    paths = sorted({asset["storage_path"] for images in chosen.values() for asset in images})
    links: dict[str, str] = {}
    if paths:
        try:
            bucket = db.storage.from_(STORAGE_BUCKET)
            signed = bucket.create_signed_urls(paths, PREVIEW_LINK_SECONDS)
            links = {s["path"]: url for s in signed if (url := s["signedURL"]) and not s["error"]}
        except Exception as exc:
            log.warning("Could not sign preview images: %s", exc)
    return {
        draft_id: [links[a["storage_path"]] for a in images if a["storage_path"] in links]
        for draft_id, images in chosen.items()
    }
