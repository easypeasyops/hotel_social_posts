from typing import Any
from urllib.parse import quote  # noqa: I001

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.assets import service as asset_service
from app.auth.dependencies import require_operator
from app.auth.upload_tokens import UPLOAD_TOKEN_TTL_SECONDS, create_upload_token
from app.content import service as content_service
from app.content.preview import image_choices, review_images
from app.database import get_supabase
from app.hotels import service as hotel_service
from app.hotels import staff as staff_service
from app.hotels.invites import create_invite, list_invites, revoke_invite
from app.hotels.models import HotelCreate, HotelUpdate
from app.jobs import tasks
from supabase import Client

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
STAFF_ROLE_LABELS = {
    "hotel_admin": "Hotel admin",
    "content_moderator": "Content moderator",
    "content_creator": "Content creator",
}


def _detail_context(
    request: Request,
    db: Client,
    hotel_id: str,
    upload_link: str | None = None,
    staff_invite_link: str | None = None,
    staff_invite_email: str | None = None,
    staff_invite_sent: bool = False,
    staff_invite_error: str | None = None,
) -> dict:
    hotel = hotel_service.get_hotel(db, hotel_id)
    assets = asset_service.list_assets(db, hotel_id)
    decided = [
        d for status in DECIDED_STATUSES for d in content_service.list_drafts(db, hotel_id, status)
    ]
    decided.sort(key=lambda d: d.get("created_at") or "", reverse=True)
    pending = content_service.list_drafts(db, hotel_id, "pending_review")
    previews, thumbnails = review_images(db, assets, pending)
    return {
        "request": request,
        "hotel": hotel,
        "assets": assets,
        "pending": pending,
        "preview_images": previews,
        "image_choices": image_choices(assets),
        "thumbnails": thumbnails,
        "decided": decided[:10],
        "upload_link": upload_link,
        "upload_link_expires_hours": UPLOAD_TOKEN_TTL_SECONDS // 3600,
        "staff": staff_service.list_members(db, hotel_id),
        "invites": list_invites(db, str(request.base_url), hotel_id),
        "staff_invite_link": staff_invite_link,
        "staff_invite_email": staff_invite_email,
        "staff_invite_sent": staff_invite_sent,
        "staff_invite_error": staff_invite_error,
        "staff_roles": STAFF_ROLE_LABELS,
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
    invite_retention_days: str | None = Form(None),
    db: Client = Depends(get_supabase),
):
    current = hotel_service.get_hotel(db, hotel_id)
    try:
        payload = HotelUpdate(
            name=name,
            location=location,
            description=description,
            tier=tier,
            channels=channels,
            contact_email=contact_email,
            invite_retention_days=invite_retention_days,
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


@router.post("/hotels/{hotel_id}/staff-invite")
def send_staff_invite(
    hotel_id: str,
    request: Request,
    email: str = Form(...),
    role: str = Form("hotel_admin"),
    valid_days: int = Form(7, ge=1, le=30),
    user=Depends(require_operator),
    db: Client = Depends(get_supabase),
):
    """Records an invite for one person, in this role, and emails it where SMTP is set up;
    only their address can sign up with it (/signup)."""
    hotel = hotel_service.get_hotel(db, hotel_id)
    if role not in staff_service.ROLES:
        raise HTTPException(status_code=422, detail="Unknown staff role")
    status_code, outcome = 200, dict[str, Any]()
    if "@" not in email.strip():
        status_code, outcome = 422, {"staff_invite_error": "Enter an email address."}
    else:
        link, sent = create_invite(
            db, str(request.base_url), hotel, role, email, valid_days, user.email
        )
        outcome = {
            "staff_invite_link": link,
            "staff_invite_email": email.strip().lower(),
            "staff_invite_sent": sent,
        }
    response = templates.TemplateResponse(
        request,
        "dashboard/hotel_detail.html",
        _detail_context(request, db, hotel_id, **outcome),
        status_code=status_code,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/hotels/{hotel_id}/staff/{user_id}/remove")
def remove_staff(hotel_id: str, user_id: str, db: Client = Depends(get_supabase)):
    staff_service.remove_member(db, hotel_id, user_id)
    return RedirectResponse(f"/dashboard/hotels/{hotel_id}#staff", status_code=303)


@router.post("/hotels/{hotel_id}/invites/{invite_id}/revoke")
def revoke_staff_invite(
    hotel_id: str,
    invite_id: str,
    user=Depends(require_operator),
    db: Client = Depends(get_supabase),
):
    revoke_invite(db, hotel_id, invite_id, user.email)
    return RedirectResponse(f"/dashboard/hotels/{hotel_id}#invites", status_code=303)


@router.post("/hotels/{hotel_id}/staff/{user_id}/role")
def change_staff_role(
    hotel_id: str, user_id: str, role: str = Form(...), db: Client = Depends(get_supabase)
):
    if role not in staff_service.ROLES:
        raise HTTPException(status_code=422, detail="Unknown staff role")
    staff_service.set_role(db, hotel_id, user_id, role)
    return RedirectResponse(f"/dashboard/hotels/{hotel_id}#staff", status_code=303)


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


@router.post("/hotels/{hotel_id}/drafts/{draft_id}/edit")
def edit_draft(
    hotel_id: str,
    draft_id: str,
    body_tr: str = Form(...),
    db: Client = Depends(get_supabase),
):
    """Save a pending draft's edited text; its translations are made again. A draft decided
    meanwhile stays as it was."""
    _hotels_draft(db, hotel_id, draft_id)
    content_service.edit_draft_text(db, draft_id, body_tr)
    return RedirectResponse(f"/dashboard/hotels/{hotel_id}#draft-{draft_id}", status_code=303)


@router.post("/hotels/{hotel_id}/drafts/{draft_id}/images")
def choose_draft_images(
    hotel_id: str,
    draft_id: str,
    choice: list[str] = Form([]),
    order: list[str] = Form([]),
    asset_ids: list[str] = Form([]),
    db: Client = Depends(get_supabase),
):
    """Save which of the hotel's photos a pending draft carries, in the order given."""
    _hotels_draft(db, hotel_id, draft_id)
    choices = image_choices(asset_service.list_assets(db, hotel_id))
    chosen = content_service.chosen_images(choice, order, asset_ids)
    content_service.set_draft_images(db, draft_id, chosen, choices)
    return RedirectResponse(f"/dashboard/hotels/{hotel_id}#draft-{draft_id}", status_code=303)


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
