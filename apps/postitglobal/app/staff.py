"""The hotel staff's own pages (/hotel): their hotel's files, a way to upload more, and the
drafts waiting for their decision. Every route acts on the hotel the signed-in account belongs
to (require_staff), never on one a URL names."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.assets import service as asset_service
from app.auth.dependencies import require_staff
from app.auth.upload_tokens import create_upload_token
from app.content import service as content_service
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
            "pending_count": len(content_service.list_drafts(db, hotel_id, "pending_review")),
        },
    )


@router.get("/upload")
def staff_upload(hotel_id: str = Depends(require_staff), db: Client = Depends(get_supabase)):
    """The upload page with a fresh upload link for the staff member's own hotel."""
    hotel = hotel_service.get_hotel(db, hotel_id)
    capability = quote(create_upload_token(hotel_id), safe="")
    return RedirectResponse(f"/upload/{quote(hotel['slug'], safe='')}#token={capability}", 303)


def _own_draft(db: Client, hotel_id: str, draft_id: str) -> dict:
    """The draft, if it belongs to the staff member's hotel: a URL can't reach another's."""
    draft = content_service.get_draft(db, draft_id)
    if draft.get("hotel_id") != hotel_id:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@router.get("/drafts", name="staff_drafts")
def staff_drafts(
    request: Request,
    hotel_id: str = Depends(require_staff),
    db: Client = Depends(get_supabase),
):
    return templates.TemplateResponse(
        request,
        "staff/drafts.html",
        {
            "request": request,
            "hotel": hotel_service.get_hotel(db, hotel_id),
            "pending": content_service.list_drafts(db, hotel_id, "pending_review"),
            "asset_names": {
                a["id"]: a["filename"] for a in asset_service.list_assets(db, hotel_id)
            },
            "done": request.query_params.get("done"),
        },
    )


@router.post("/drafts/{draft_id}/approve")
def staff_approve(
    draft_id: str, hotel_id: str = Depends(require_staff), db: Client = Depends(get_supabase)
):
    """As on the dashboard: publish to Buffer through the worker; a second click does nothing."""
    if _own_draft(db, hotel_id, draft_id).get("status") == "pending_review":
        try:
            content_service.approve_draft(db, draft_id)
        except HTTPException as exc:
            if exc.status_code != 404:  # someone else decided it a moment ago
                raise
    return RedirectResponse("/hotel/drafts?done=approved", status_code=303)


@router.post("/drafts/{draft_id}/reject")
def staff_reject(
    draft_id: str,
    feedback: str = Form(""),
    hotel_id: str = Depends(require_staff),
    db: Client = Depends(get_supabase),
):
    if _own_draft(db, hotel_id, draft_id).get("status") == "pending_review":
        content_service.reject_draft(db, draft_id, feedback.strip() or None)
    return RedirectResponse("/hotel/drafts?done=rejected", status_code=303)
