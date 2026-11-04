from urllib.parse import quote  # noqa: I001

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from supabase import Client

from app.assets import service as asset_service
from app.auth.dependencies import require_operator
from app.auth.upload_tokens import create_upload_token, UPLOAD_TOKEN_TTL_SECONDS
from app.content import service as content_service
from app.database import get_supabase
from app.hotels import service as hotel_service
from app.hotels.models import HotelCreate, HotelUpdate
from app.jobs import tasks

router = APIRouter(prefix="/dashboard", dependencies=[Depends(require_operator)])
templates = Jinja2Templates(directory="app/templates")


def _hotel_form_context(request: Request, hotel: dict | None = None, error: str | None = None):
    return {
        "request": request,
        "hotel": hotel,
        "error": error,
        "tiers": ["standard", "growth", "premium"],
        "channels": ["instagram", "facebook", "tiktok", "google_business"],
    }


# What the review section lists besides the drafts waiting for a decision: how the latest
# decisions went (queued at Buffer, published by it, or failed), so an operator sees the outcome.
DECIDED_STATUSES = ("approved", "scheduled", "published", "failed")


def _detail_context(
    request: Request, db: Client, hotel_id: str, upload_link: str | None = None
) -> dict:
    hotel = hotel_service.get_hotel(db, hotel_id)
    assets = asset_service.list_assets(db, hotel_id)
    decided = [
        d for status in DECIDED_STATUSES for d in content_service.list_drafts(db, hotel_id, status)
    ]
    decided.sort(key=lambda d: d.get("created_at") or "", reverse=True)
    return {
        "request": request,
        "hotel": hotel,
        "assets": assets,
        "asset_names": {a["id"]: a["filename"] for a in assets},
        "pending": content_service.list_drafts(db, hotel_id, "pending_review"),
        "decided": decided[:10],
        "upload_link": upload_link,
        "upload_link_expires_hours": UPLOAD_TOKEN_TTL_SECONDS // 3600,
        "generation_queued": request.query_params.get("generation") == "queued",
        "deletable": content_service.DELETABLE_STATUSES,
    }


def _hotels_draft(db: Client, hotel_id: str, draft_id: str) -> dict:
    """The draft, if it belongs to this hotel: a URL can't act on another hotel's draft."""
    draft = content_service.get_draft(db, draft_id)
    if draft.get("hotel_id") != hotel_id:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@router.get("")
def dashboard_home():
    return RedirectResponse("/dashboard/hotels", status_code=303)


@router.get("/hotels")
def list_hotels(request: Request, db: Client = Depends(get_supabase)):
    hotels = hotel_service.list_hotels(db)
    return templates.TemplateResponse(
        request, "dashboard/hotels.html", {"request": request, "hotels": hotels}
    )


@router.get("/hotels/new")
def new_hotel_page(request: Request):
    return templates.TemplateResponse(
        request, "dashboard/hotel_form.html", _hotel_form_context(request)
    )


@router.post("/hotels")
def create_hotel(
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
def hotel_detail(
    hotel_id: str,
    request: Request,
    db: Client = Depends(get_supabase),
):
    return templates.TemplateResponse(
        request, "dashboard/hotel_detail.html", _detail_context(request, db, hotel_id)
    )


@router.get("/hotels/{hotel_id}/edit")
def edit_hotel_page(
    hotel_id: str,
    request: Request,
    db: Client = Depends(get_supabase),
):
    hotel = hotel_service.get_hotel(db, hotel_id)
    return templates.TemplateResponse(
        request, "dashboard/hotel_form.html", _hotel_form_context(request, hotel)
    )


@router.post("/hotels/{hotel_id}")
def update_hotel(
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
def create_hotel_upload_link(
    hotel_id: str,
    request: Request,
    db: Client = Depends(get_supabase),
):
    hotel = hotel_service.get_hotel(db, hotel_id)
    capability = create_upload_token(hotel_id)
    page_url = f"/upload/{quote(hotel['slug'], safe='')}"
    upload_link = (
        f"{str(request.base_url).rstrip('/')}{page_url}#token={quote(capability, safe='')}"
    )
    response = templates.TemplateResponse(
        request,
        "dashboard/hotel_detail.html",
        _detail_context(request, db, hotel_id, upload_link),
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/hotels/{hotel_id}/generate")
def generate_drafts(hotel_id: str, db: Client = Depends(get_supabase)):
    """Queue draft generation for this hotel now, as the weekly CronJob does for every hotel:
    the worker writes a draft per channel (Claude), then translates them (DeepL)."""
    hotel_service.get_hotel(db, hotel_id)  # 404 for an unknown hotel, before queueing
    tasks.generate_content_task.delay(hotel_id)
    return RedirectResponse(
        f"/dashboard/hotels/{hotel_id}?generation=queued#review", status_code=303
    )


@router.post("/hotels/{hotel_id}/drafts/{draft_id}/approve")
def approve_draft(hotel_id: str, draft_id: str, db: Client = Depends(get_supabase)):
    """Approve a draft waiting for review: it is published to Buffer by the worker. A second
    click (the draft is no longer pending) changes nothing and just returns to the page."""
    _hotels_draft(db, hotel_id, draft_id)
    try:
        content_service.approve_draft(db, draft_id)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    return RedirectResponse(f"/dashboard/hotels/{hotel_id}#review", status_code=303)


@router.post("/hotels/{hotel_id}/drafts/{draft_id}/delete")
def delete_draft(hotel_id: str, draft_id: str, db: Client = Depends(get_supabase)):
    """Delete a draft that isn't at Buffer (pending, rejected or failed), with what hangs on it."""
    content_service.delete_draft(db, _hotels_draft(db, hotel_id, draft_id))
    return RedirectResponse(f"/dashboard/hotels/{hotel_id}#review", status_code=303)


@router.post("/hotels/{hotel_id}/assets/{asset_id}/delete")
def delete_asset(hotel_id: str, asset_id: str, db: Client = Depends(get_supabase)):
    """Delete an uploaded file and its record. Drafts that named it publish without it."""
    if asset_service.get_asset(db, asset_id).get("hotel_id") != hotel_id:
        raise HTTPException(status_code=404, detail="Asset not found")
    asset_service.delete_asset(db, asset_id)
    return RedirectResponse(f"/dashboard/hotels/{hotel_id}#media", status_code=303)


@router.post("/hotels/{hotel_id}/drafts/{draft_id}/reject")
def reject_draft(
    hotel_id: str,
    draft_id: str,
    feedback: str = Form(""),
    db: Client = Depends(get_supabase),
):
    """Reject a draft waiting for review, with optional feedback; it is never published."""
    draft = _hotels_draft(db, hotel_id, draft_id)
    if draft.get("status") == "pending_review":
        content_service.reject_draft(db, draft_id, feedback.strip() or None)
    return RedirectResponse(f"/dashboard/hotels/{hotel_id}#review", status_code=303)
