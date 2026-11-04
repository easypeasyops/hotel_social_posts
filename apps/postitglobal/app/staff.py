"""The hotel staff's own pages (/hotel): their hotel's files and a way to upload more. Every
route acts on the hotel the signed-in account belongs to (require_staff), never on one a URL
names."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.assets import service as asset_service
from app.auth.dependencies import require_staff
from app.auth.upload_tokens import create_upload_token
from app.database import get_supabase
from app.hotels import service as hotel_service
from supabase import Client

router = APIRouter(prefix="/hotel")
templates = Jinja2Templates(directory="app/templates")


@router.get("", name="staff_home")
def staff_home(
    request: Request,
    hotel_id: str = Depends(require_staff),
    db: Client = Depends(get_supabase),
):
    return templates.TemplateResponse(
        request,
        "staff/home.html",
        {
            "request": request,
            "hotel": hotel_service.get_hotel(db, hotel_id),
            "assets": asset_service.list_assets(db, hotel_id),
        },
    )


@router.get("/upload")
def staff_upload(hotel_id: str = Depends(require_staff), db: Client = Depends(get_supabase)):
    """The upload page with a fresh upload link for the staff member's own hotel."""
    hotel = hotel_service.get_hotel(db, hotel_id)
    capability = quote(create_upload_token(hotel_id), safe="")
    return RedirectResponse(f"/upload/{quote(hotel['slug'], safe='')}#token={capability}", 303)
