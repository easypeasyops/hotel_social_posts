import uuid

from fastapi import HTTPException

from app.assets.models import UploadUrlRequest, UploadUrlResponse
from supabase import Client

STORAGE_BUCKET = "hotel-assets"


def list_assets(db: Client, hotel_id: str) -> list[dict]:
    response = (
        db.table("assets")
        .select("*")
        .eq("hotel_id", hotel_id)
        .order("created_at", desc=True)
        .execute()
    )
    return response.data


def get_asset(db: Client, asset_id: str) -> dict:
    response = db.table("assets").select("*").eq("id", asset_id).single().execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Asset not found")
    return response.data


def create_upload_url(db: Client, hotel_id: str, request: UploadUrlRequest) -> UploadUrlResponse:
    """
    Pre-creates an asset record in 'pending' status and returns a
    presigned upload URL for direct-to-Supabase-Storage upload.
    """
    asset_id = str(uuid.uuid4())
    storage_path = f"{hotel_id}/{asset_id}/{request.filename}"

    # Pre-create asset record
    db.table("assets").insert(
        {
            "id": asset_id,
            "hotel_id": hotel_id,
            "filename": request.filename,
            "category": request.category.value,
            "storage_path": storage_path,
            "status": "pending",
        }
    ).execute()

    # Generate presigned upload URL (60 min expiry)
    signed = db.storage.from_(STORAGE_BUCKET).create_signed_upload_url(storage_path)

    return UploadUrlResponse(
        upload_url=signed["signedURL"],
        storage_path=storage_path,
        asset_id=asset_id,
    )


def confirm_upload(db: Client, asset_id: str, expected_hotel_id: str | None = None) -> dict:
    """
    Called after a successful upload. Marks asset as 'processing'
    and enqueues the process_asset Celery task.
    """
    from app.jobs.tasks import process_asset_task  # avoid circular import

    query = (
        db.table("assets")
        .update({"status": "processing"})
        .eq("id", asset_id)
        .eq("status", "pending")
    )
    if expected_hotel_id is not None:
        query = query.eq("hotel_id", expected_hotel_id)
    response = query.execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Asset not found or already confirmed")

    process_asset_task.delay(asset_id)
    return response.data[0]


def delete_asset(db: Client, asset_id: str) -> None:
    asset = get_asset(db, asset_id)
    db.storage.from_(STORAGE_BUCKET).remove([asset["storage_path"]])
    db.table("assets").delete().eq("id", asset_id).execute()
