from fastapi import HTTPException

from supabase import Client


def list_drafts(db: Client, hotel_id: str, status: str) -> list[dict]:
    return (
        db.table("content_drafts")
        .select("*")
        .eq("hotel_id", hotel_id)
        .eq("status", status)
        .order("created_at", desc=True)
        .execute()
        .data
    )


def get_draft(db: Client, draft_id: str) -> dict:
    response = db.table("content_drafts").select("*").eq("id", draft_id).single().execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Draft not found")
    return response.data


def approve_draft(db: Client, draft_id: str) -> dict:
    from app.jobs.tasks import publish_content_task  # avoid circular import

    response = (
        db.table("content_drafts")
        .update({"status": "approved"})
        .eq("id", draft_id)
        .eq("status", "pending_review")
        .execute()
    )
    if not response.data:
        raise HTTPException(
            status_code=404, detail="Draft not found or not in pending_review state"
        )

    publish_content_task.delay(draft_id)
    return response.data[0]


def edit_draft_text(db: Client, draft_id: str, body_tr: str) -> bool:
    """Replace the Turkish text of a draft still waiting for review, and make its
    translations again from it. False when the draft has been decided meanwhile: it stays as
    it was. Empty text is refused (422)."""
    from app.jobs.tasks import translate_content_task  # avoid circular import

    body_tr = body_tr.strip()
    if not body_tr:
        raise HTTPException(status_code=422, detail="The post's text can't be empty")
    response = (
        db.table("content_drafts")
        .update({"body_tr": body_tr})
        .eq("id", draft_id)
        .eq("status", "pending_review")
        .execute()
    )
    if not response.data:
        return False
    translate_content_task.delay(draft_id)
    return True


def chosen_images(choice: list[str], order: list[str], ticked: list[str]) -> list[str]:
    """The ticked photos in the order given: `choice` lists every offered photo and `order`
    its order box (a number, or blank), as the picker's form sends them. Ticked photos
    without a number follow the numbered ones, as offered."""
    position = {asset_id: n for n, asset_id in enumerate(choice)}
    given = dict(zip(choice, order, strict=False))

    def key(asset_id: str) -> tuple[float, int]:
        number = given.get(asset_id, "").strip()
        return (float(number) if number.isdigit() else float("inf"), position.get(asset_id, 0))

    return sorted(dict.fromkeys(ticked), key=key)


def set_draft_images(db: Client, draft_id: str, asset_ids: list[str], choices: list[dict]) -> bool:
    """Give a draft still waiting for review these photos, in this order. Each must be one
    of `choices` (the hotel's photos a post can carry), at most MAX_IMAGES: else 422. False
    when the draft has been decided meanwhile: it stays as it was."""
    from app.publishing.buffer import MAX_IMAGES  # avoid a circular import

    allowed = {a["id"] for a in choices}
    if any(asset_id not in allowed for asset_id in asset_ids):
        raise HTTPException(status_code=422, detail="Only the hotel's ready photos can be chosen")
    if len(asset_ids) > MAX_IMAGES:
        raise HTTPException(status_code=422, detail=f"A post carries at most {MAX_IMAGES} photos")
    response = (
        db.table("content_drafts")
        .update({"asset_ids": asset_ids})
        .eq("id", draft_id)
        .eq("status", "pending_review")
        .execute()
    )
    return bool(response.data)


# Drafts that can be deleted: none of them is at Buffer. An approved draft is being published
# and a scheduled one is in Buffer's queue: deleting the row wouldn't take the post back.
DELETABLE_STATUSES = ("pending_review", "rejected", "failed")


def delete_draft(db: Client, draft: dict) -> None:
    """Delete a draft, its translations and publish log (cascade), and the image copies an
    attempt to publish it made in the public bucket (<hotel>/<draft>/)."""
    from app.publishing.buffer import PUBLISHED_BUCKET  # avoid a circular import

    if draft["status"] not in DELETABLE_STATUSES:
        raise HTTPException(status_code=409, detail=f"A {draft['status']} draft can't be deleted")
    published = db.storage.from_(PUBLISHED_BUCKET)
    prefix = f"{draft['hotel_id']}/{draft['id']}"
    copies = [f"{prefix}/{f['name']}" for f in published.list(prefix)]
    if copies:
        published.remove(copies)
    db.table("content_drafts").delete().eq("id", draft["id"]).execute()


def reject_draft(db: Client, draft_id: str, feedback: str | None) -> dict:
    update_data = {"status": "rejected"}
    if feedback:
        update_data["operator_feedback"] = feedback

    response = db.table("content_drafts").update(update_data).eq("id", draft_id).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Draft not found")
    return response.data[0]


def get_translations(db: Client, draft_id: str) -> list[dict]:
    return db.table("content_translations").select("*").eq("draft_id", draft_id).execute().data
