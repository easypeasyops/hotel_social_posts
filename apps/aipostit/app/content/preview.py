"""What a draft's post preview shows: the images publishing will send (postable_images),
through signed links, since `hotel-assets` is private."""

import logging
from typing import Any

from app.assets.service import STORAGE_BUCKET
from app.publishing.buffer import IMAGE_TYPES, image_suffix, postable_images
from supabase import Client

log = logging.getLogger(__name__)

# Long enough to review a page of drafts, short enough not to be a lasting link to the files.
PREVIEW_LINK_SECONDS = 3600


def _signed_links(db: Client, paths: set[str]) -> dict[str, str]:
    """A signed link for each of `paths`, in one Storage request. If Storage fails, none: the
    page still shows, without images."""
    if not paths:
        return {}
    try:
        signed = db.storage.from_(STORAGE_BUCKET).create_signed_urls(
            sorted(paths), PREVIEW_LINK_SECONDS
        )
    except Exception as exc:
        log.warning("Could not sign preview images: %s", exc)
        return {}
    return {s["path"]: url for s in signed if (url := s["signedURL"]) and not s["error"]}


def _postable(
    assets: list[dict[str, Any]], drafts: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    ready = [asset for asset in assets if asset.get("status") == "ready"]
    return {d["id"]: postable_images(ready, d.get("asset_ids") or []) for d in drafts}


def _previews(
    chosen: dict[str, list[dict[str, Any]]], links: dict[str, str]
) -> dict[str, list[str]]:
    return {
        draft_id: [links[a["storage_path"]] for a in images if a["storage_path"] in links]
        for draft_id, images in chosen.items()
    }


def preview_images(
    db: Client, assets: list[dict[str, Any]], drafts: list[dict[str, Any]]
) -> dict[str, list[str]]:
    """Each draft's postable images as signed links, in the draft's order, from the hotel's
    `assets`; one Storage request for them all. If Storage fails, no images: the text can
    still be reviewed."""
    chosen = _postable(assets, drafts)
    paths = {asset["storage_path"] for images in chosen.values() for asset in images}
    return _previews(chosen, _signed_links(db, paths))


def image_choices(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The hotel's photos a post can carry, as `assets` lists them: ready JPEG and PNG
    files (posts carry no video yet)."""
    return [a for a in assets if a.get("status") == "ready" and image_suffix(a) in IMAGE_TYPES]


def thumbnail_of(asset: dict[str, Any]) -> str:
    """A photo's small copy (app/assets/thumbnails.py), or the photo itself until the worker
    has made one."""
    return asset.get("thumbnail_path") or asset["storage_path"]


def review_images(
    db: Client, assets: list[dict[str, Any]], drafts: list[dict[str, Any]]
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """What a review page shows: each draft's preview images (full size), and a thumbnail
    link for each photo a draft can be given (image_choices), in one Storage request."""
    chosen, choices = _postable(assets, drafts), image_choices(assets)
    paths = {asset["storage_path"] for images in chosen.values() for asset in images}
    links = _signed_links(db, paths | {thumbnail_of(a) for a in choices})
    thumbnails = {a["id"]: links[thumbnail_of(a)] for a in choices if thumbnail_of(a) in links}
    return _previews(chosen, links), thumbnails


def photo_links(db: Client, assets: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, str]]:
    """The hotel's photos (image_choices) as thumbnail links and full-size links, by asset id,
    in one Storage request."""
    choices = image_choices(assets)
    links = _signed_links(db, {p for a in choices for p in (thumbnail_of(a), a["storage_path"])})
    thumbnails = {a["id"]: links[thumbnail_of(a)] for a in choices if thumbnail_of(a) in links}
    originals = {a["id"]: links[a["storage_path"]] for a in choices if a["storage_path"] in links}
    return thumbnails, originals
