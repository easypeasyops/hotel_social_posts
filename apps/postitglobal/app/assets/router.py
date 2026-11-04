from fastapi import APIRouter, Depends

from app.assets import service
from app.assets.models import UploadUrlRequest
from app.auth.dependencies import require_operator
from app.database import get_supabase
from supabase import Client

router = APIRouter()


@router.get("/hotel/{hotel_id}")
def list_assets(
    hotel_id: str,
    db: Client = Depends(get_supabase),
    _user=Depends(require_operator),
):
    return service.list_assets(db, hotel_id)


@router.post("/hotel/{hotel_id}/upload-url", status_code=201)
def create_upload_url(
    hotel_id: str,
    request: UploadUrlRequest,
    db: Client = Depends(get_supabase),
    _user=Depends(require_operator),
):
    return service.create_upload_url(db, hotel_id, request)


@router.post("/{asset_id}/confirm")
def confirm_upload(
    asset_id: str,
    db: Client = Depends(get_supabase),
    _user=Depends(require_operator),
):
    return service.confirm_upload(db, asset_id)


@router.delete("/{asset_id}", status_code=204)
def delete_asset(
    asset_id: str,
    db: Client = Depends(get_supabase),
    _user=Depends(require_operator),
):
    service.delete_asset(db, asset_id)
