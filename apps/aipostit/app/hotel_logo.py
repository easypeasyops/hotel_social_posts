"""A hotel's logo, set by an operator on the hotel's dashboard page or by the hotel's admin on
/hotel/details: fitted whole into a square WebP (make_photo with logo=True) and kept in the
private hotel-assets bucket at hotel-logos/{hotel_id}.webp, replacing the last one.
hotels.logo_version (migration 007), the upload's time, says there is one and goes in its URL,
so a browser caches each logo for good. It is shown in the app only, never in posts."""

import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse, Response

from app.assets.service import STORAGE_BUCKET
from app.auth.dependencies import (
    get_current_user,
    is_operator,
    require_hotel_admin,
    require_operator,
)
from app.database import get_supabase
from app.hotels import service as hotel_service
from app.hotels.staff import member_of
from app.profile_photo import MAX_UPLOAD_BYTES, make_photo
from supabase import Client

router = APIRouter()


def logo_path(hotel_id: str) -> str:
    return f"hotel-logos/{hotel_id}.webp"


def _save(db: Client, hotel_id: str, upload: UploadFile) -> str:
    """Store the upload as the hotel's logo: "saved", or "invalid" for a file that isn't a
    JPEG, PNG or WebP image of up to 5 MB (nothing is stored then)."""
    data = upload.file.read(MAX_UPLOAD_BYTES + 1)
    try:
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError("too big")
        webp = make_photo(data, logo=True)
    except ValueError:
        return "invalid"
    db.storage.from_(STORAGE_BUCKET).upload(
        logo_path(hotel_id), webp, {"content-type": "image/webp", "upsert": "true"}
    )
    db.table("hotels").update({"logo_version": int(time.time())}).eq("id", hotel_id).execute()
    return "saved"


def _remove(db: Client, hotel_id: str) -> str:
    db.storage.from_(STORAGE_BUCKET).remove([logo_path(hotel_id)])
    db.table("hotels").update({"logo_version": None}).eq("id", hotel_id).execute()
    return "removed"


@router.post("/dashboard/hotels/{hotel_id}/logo", dependencies=[Depends(require_operator)])
def operator_upload_logo(
    hotel_id: str, logo: UploadFile = File(...), db: Client = Depends(get_supabase)
):
    hotel_service.get_hotel(db, hotel_id)  # 404 for an unknown hotel
    outcome = _save(db, hotel_id, logo)
    return RedirectResponse(f"/dashboard/hotels/{hotel_id}?logo={outcome}#logo", 303)


@router.post("/dashboard/hotels/{hotel_id}/logo/remove", dependencies=[Depends(require_operator)])
def operator_remove_logo(hotel_id: str, db: Client = Depends(get_supabase)):
    hotel_service.get_hotel(db, hotel_id)
    return RedirectResponse(f"/dashboard/hotels/{hotel_id}?logo={_remove(db, hotel_id)}#logo", 303)


@router.post("/hotel/details/logo")
def admin_upload_logo(
    logo: UploadFile = File(...),
    hotel_id: str = Depends(require_hotel_admin),
    db: Client = Depends(get_supabase),
):
    return RedirectResponse(f"/hotel/details?logo={_save(db, hotel_id, logo)}#logo", 303)


@router.post("/hotel/details/logo/remove")
def admin_remove_logo(
    hotel_id: str = Depends(require_hotel_admin), db: Client = Depends(get_supabase)
):
    return RedirectResponse(f"/hotel/details?logo={_remove(db, hotel_id)}#logo", 303)


@router.get("/logos/{hotel_id}")
def hotel_logo(hotel_id: str, user=Depends(get_current_user), db: Client = Depends(get_supabase)):
    """The logo, for operators and the hotel's own staff; its URL changes with each upload
    (?v=), so it can be cached."""
    if not is_operator(user) and (member_of(db, user.id) or {}).get("hotel_id") != hotel_id:
        raise HTTPException(status_code=404)
    try:
        data = db.storage.from_(STORAGE_BUCKET).download(logo_path(hotel_id))
    except Exception as exc:  # no logo, or it is gone
        raise HTTPException(status_code=404) from exc
    return Response(
        data, media_type="image/webp", headers={"Cache-Control": "private, max-age=31536000"}
    )
