from fastapi import APIRouter, Depends

from app.assets import service
from app.assets.models import UploadUrlRequest
from app.auth.dependencies import verify_hotel_upload_token
from app.database import get_supabase
from supabase import Client

router = APIRouter(
    prefix="/api/v1/upload-capabilities",
    dependencies=[Depends(verify_hotel_upload_token)],
)


@router.post("/{hotel_id}/upload-url", status_code=201)
async def create_upload_url(
    hotel_id: str,
    request: UploadUrlRequest,
    db: Client = Depends(get_supabase),
):
    return service.create_upload_url(db, hotel_id, request)


@router.post("/{hotel_id}/assets/{asset_id}/confirm")
async def confirm_upload(
    hotel_id: str,
    asset_id: str,
    db: Client = Depends(get_supabase),
):
    return service.confirm_upload(db, asset_id, expected_hotel_id=hotel_id)
