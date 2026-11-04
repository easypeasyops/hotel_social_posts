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
