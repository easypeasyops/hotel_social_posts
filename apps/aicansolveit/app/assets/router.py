from fastapi import APIRouter, Depends

from app.assets import service
from app.assets.models import UploadUrlRequest
from app.auth.dependencies import get_current_user
from app.database import get_supabase
from supabase import Client

router = APIRouter()


@router.get("/hotel/{hotel_id}")
async def list_assets(
    hotel_id: str,
    db: Client = Depends(get_supabase),
    _user=Depends(get_current_user),
):
    return service.list_assets(db, hotel_id)


@router.post("/hotel/{hotel_id}/upload-url", status_code=201)
async def create_upload_url(
    hotel_id: str,
    request: UploadUrlRequest,
    db: Client = Depends(get_supabase),
    _user=Depends(get_current_user),
):
    return service.create_upload_url(db, hotel_id, request)


@router.post("/{asset_id}/confirm")
async def confirm_upload(
    asset_id: str,
    db: Client = Depends(get_supabase),
    _user=Depends(get_current_user),
):
    return service.confirm_upload(db, asset_id)


@router.delete("/{asset_id}", status_code=204)
async def delete_asset(
    asset_id: str,
    db: Client = Depends(get_supabase),
    _user=Depends(get_current_user),
):
    service.delete_asset(db, asset_id)
