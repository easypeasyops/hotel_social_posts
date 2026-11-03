from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from supabase import Client

from app.assets import service as asset_service
from app.auth.dependencies import get_current_user
from app.auth.upload_tokens import create_upload_token, UPLOAD_TOKEN_TTL_SECONDS
from app.database import get_supabase
from app.hotels import service as hotel_service
from app.hotels.models import HotelCreate, HotelUpdate

router = APIRouter(prefix="/dashboard", dependencies=[Depends(get_current_user)])
templates = Jinja2Templates(directory="app/templates")


def _hotel_form_context(request: Request, hotel: dict | None = None, error: str | None = None):
    return {
        "request": request,
        "hotel": hotel,
        "error": error,
        "tiers": ["standard", "growth", "premium"],
        "channels": ["instagram", "facebook", "tiktok", "google_business"],
    }


@router.get("")
async def dashboard_home():
    return RedirectResponse("/dashboard/hotels", status_code=303)


@router.get("/hotels")
async def list_hotels(request: Request, db: Client = Depends(get_supabase)):
    hotels = hotel_service.list_hotels(db)
    return templates.TemplateResponse(
        request,
        "dashboard/hotels.html", {"request": request, "hotels": hotels}
    )


@router.get("/hotels/new")
async def new_hotel_page(request: Request):
    return templates.TemplateResponse(
        request,
        "dashboard/hotel_form.html", _hotel_form_context(request)
    )


@router.post("/hotels")
async def create_hotel(
    request: Request,
    name: str = Form(...),
    slug: str = Form(...),
    location: str = Form(...),
    contact_email: str = Form(...),
    tier: str = Form("standard"),
    channels: list[str] = Form(default=[]),
    description: str = Form(""),
    db: Client = Depends(get_supabase),
):
    try:
        payload = HotelCreate(
            name=name,
            slug=slug,
            location=location,
            contact_email=contact_email,
            tier=tier,
            channels=channels,
            description=description or None,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "dashboard/hotel_form.html",
            _hotel_form_context(request, error=str(exc)),
            status_code=422,
        )

    hotel = hotel_service.create_hotel(db, payload)
    return RedirectResponse(f"/dashboard/hotels/{hotel['id']}", status_code=303)


@router.get("/hotels/{hotel_id}")
async def hotel_detail(
    hotel_id: str,
    request: Request,
    db: Client = Depends(get_supabase),
):
    hotel = hotel_service.get_hotel(db, hotel_id)
    assets = asset_service.list_assets(db, hotel_id)
    return templates.TemplateResponse(
        request,
        "dashboard/hotel_detail.html",
        {
            "request": request,
            "hotel": hotel,
            "assets": assets,
            "upload_link": None,
            "upload_link_expires_hours": UPLOAD_TOKEN_TTL_SECONDS // 3600,
        },
    )


@router.get("/hotels/{hotel_id}/edit")
async def edit_hotel_page(
    hotel_id: str,
    request: Request,
    db: Client = Depends(get_supabase),
):
    hotel = hotel_service.get_hotel(db, hotel_id)
    return templates.TemplateResponse(
        request,
        "dashboard/hotel_form.html", _hotel_form_context(request, hotel)
    )


@router.post("/hotels/{hotel_id}")
async def update_hotel(
    hotel_id: str,
    request: Request,
    name: str = Form(...),
    location: str = Form(...),
    contact_email: str = Form(...),
    tier: str = Form("standard"),
    channels: list[str] = Form(default=[]),
    description: str = Form(""),
    db: Client = Depends(get_supabase),
):
    current = hotel_service.get_hotel(db, hotel_id)
    try:
        payload = HotelUpdate(
            name=name,
            description=description,
            tier=tier,
            channels=channels,
            contact_email=contact_email,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "dashboard/hotel_form.html",
            _hotel_form_context(request, current, str(exc)),
            status_code=422,
        )

    hotel_service.update_hotel(db, hotel_id, payload)
    return RedirectResponse(f"/dashboard/hotels/{hotel_id}", status_code=303)


@router.post("/hotels/{hotel_id}/upload-link")
async def create_hotel_upload_link(
    hotel_id: str,
    request: Request,
    db: Client = Depends(get_supabase),
):
    hotel = hotel_service.get_hotel(db, hotel_id)
    capability = create_upload_token(hotel_id)
    page_url = f"/upload/{quote(hotel['slug'], safe='')}"
    upload_link = (
        f"{str(request.base_url).rstrip('/')}{page_url}"
        f"#token={quote(capability, safe='')}"
    )
    assets = asset_service.list_assets(db, hotel_id)
    response = templates.TemplateResponse(
        request,
        "dashboard/hotel_detail.html",
        {
            "request": request,
            "hotel": hotel,
            "assets": assets,
            "upload_link": upload_link,
            "upload_link_expires_hours": UPLOAD_TOKEN_TTL_SECONDS // 3600,
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return response
