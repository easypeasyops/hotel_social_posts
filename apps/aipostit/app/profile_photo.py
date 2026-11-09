"""A signed-in account's own profile photo: uploaded from its profile page, kept square and small
in the private hotel-assets bucket (avatars/{user_id}.webp), and served only to that account at
/account/photo. user_metadata.photo_version, the upload's time, tells pages there is one and
keeps a browser from showing an older one from its cache."""

import time
from io import BytesIO

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse, Response
from PIL import Image, ImageOps

from app.assets.service import STORAGE_BUCKET
from app.auth.dependencies import get_current_user, is_operator
from app.database import get_supabase
from app.hotels.staff import member_of
from supabase import Client

router = APIRouter(prefix="/account/photo")

PHOTO_SIZE = 256  # px square: sharp in the menu and on the profile page on a 2x screen
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
FORMATS = ("JPEG", "PNG", "WEBP")


def photo_path(user_id: str) -> str:
    return f"avatars/{user_id}.webp"


def make_photo(data: bytes) -> bytes:
    """`data` as a PHOTO_SIZE square WebP, upright and cropped to its middle. Raises ValueError
    for anything but a JPEG, PNG or WebP image."""
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in FORMATS:
                raise ValueError(image.format)
            square = ImageOps.fit(ImageOps.exif_transpose(image), (PHOTO_SIZE, PHOTO_SIZE))
            out = BytesIO()
            square.convert("RGB").save(out, "WEBP", quality=85)
            return out.getvalue()
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("not an image") from exc


def _profile(user, db: Client) -> str:
    """The account's profile page; 403 for an account that is neither operator nor staff."""
    if is_operator(user):
        return "/dashboard/profile"
    if member_of(db, user.id) is None:
        raise HTTPException(status_code=403, detail="This account doesn't have access")
    return "/hotel/profile"


@router.post("")
def upload_photo(
    photo: UploadFile = File(...),
    user=Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    profile = _profile(user, db)
    data = photo.file.read(MAX_UPLOAD_BYTES + 1)
    try:
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError("too big")
        webp = make_photo(data)
    except ValueError:
        return RedirectResponse(f"{profile}?photo=invalid", status_code=303)
    db.storage.from_(STORAGE_BUCKET).upload(
        photo_path(user.id), webp, {"content-type": "image/webp", "upsert": "true"}
    )
    db.auth.admin.update_user_by_id(user.id, {"user_metadata": {"photo_version": int(time.time())}})
    return RedirectResponse(f"{profile}?photo=saved", status_code=303)


@router.post("/remove")
def remove_photo(user=Depends(get_current_user), db: Client = Depends(get_supabase)):
    profile = _profile(user, db)
    db.storage.from_(STORAGE_BUCKET).remove([photo_path(user.id)])
    db.auth.admin.update_user_by_id(user.id, {"user_metadata": {"photo_version": None}})
    return RedirectResponse(f"{profile}?photo=removed", status_code=303)


@router.get("")
def own_photo(user=Depends(get_current_user), db: Client = Depends(get_supabase)):
    """The account's own photo; its URL changes with each upload (?v=), so it can be cached."""
    if not (getattr(user, "user_metadata", None) or {}).get("photo_version"):
        raise HTTPException(status_code=404)
    try:
        data = db.storage.from_(STORAGE_BUCKET).download(photo_path(user.id))
    except Exception as exc:  # the object is gone though the metadata says otherwise
        raise HTTPException(status_code=404) from exc
    return Response(
        data, media_type="image/webp", headers={"Cache-Control": "private, max-age=31536000"}
    )
