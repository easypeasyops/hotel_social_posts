"""The hotel staff's own pages (/hotel): their hotel's files, a way to upload more, and the
drafts waiting for their decision. Every route acts on the hotel the signed-in account belongs
to (require_staff), never on one a URL names. Changing or deciding content takes a hotel admin
or content moderator (require_moderator); a content creator uploads and looks."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.assets import service as asset_service
from app.assets.models import AssetCategory
from app.auth.dependencies import (
    get_current_user,
    require_hotel_admin,
    require_moderator,
    require_staff,
    require_staff_member,
)
from app.auth.upload_tokens import create_upload_token
from app.content import service as content_service
from app.content.preview import image_choices, photo_links, review_images
from app.database import get_supabase
from app.hotels import service as hotel_service
from app.hotels import staff as staff_service
from app.hotels.invites import create_invite, list_invites
from app.hotels.models import HotelUpdate, SocialChannel
from app.hotels.staff import ROLES, can_moderate
from supabase import Client

router = APIRouter(prefix="/hotel")
templates = Jinja2Templates(directory="app/templates")


@router.get("", name="staff_home")
def staff_home(
    request: Request,
    member: dict = Depends(require_staff_member),
    db: Client = Depends(get_supabase),
):
    hotel_id = member["hotel_id"]
    assets = asset_service.list_assets(db, hotel_id)
    thumbnails, originals = photo_links(db, assets)
    return templates.TemplateResponse(
        request,
        "staff/home.html",
        {
            "request": request,
            "hotel": hotel_service.get_hotel(db, hotel_id),
            "assets": assets,
            "thumbnails": thumbnails,
            "originals": originals,
            "sent": content_service.sent_asset_ids(db, hotel_id),
            "can_moderate": can_moderate(member),
            "is_admin": member["role"] == "hotel_admin",
            "pending_count": len(content_service.list_drafts(db, hotel_id, "pending_review")),
        },
    )


@router.get("/upload")
def staff_upload(hotel_id: str = Depends(require_staff), db: Client = Depends(get_supabase)):
    """The upload page with a fresh upload link for the staff member's own hotel."""
    hotel = hotel_service.get_hotel(db, hotel_id)
    capability = quote(create_upload_token(hotel_id), safe="")
    return RedirectResponse(f"/upload/{quote(hotel['slug'], safe='')}#token={capability}", 303)


def _own_unsent_file(db: Client, hotel_id: str, asset_id: str) -> dict:
    """The file, if it belongs to the staff member's hotel (else 404) and no draft has taken it
    to Buffer (else 409)."""
    asset = asset_service.get_asset(db, asset_id)
    if asset.get("hotel_id") != hotel_id:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset_id in content_service.sent_asset_ids(db, hotel_id):
        raise HTTPException(status_code=409, detail="Bu dosya Buffer'a gönderilen bir paylaşımda")
    return asset


@router.post("/files/{asset_id}/edit")
def staff_edit_file(
    asset_id: str,
    name: str = Form(...),
    category: AssetCategory = Form(...),
    hotel_id: str = Depends(require_moderator),
    db: Client = Depends(get_supabase),
):
    asset_service.edit_asset(db, _own_unsent_file(db, hotel_id, asset_id), name, category)
    return RedirectResponse(f"/hotel#file-{asset_id}", status_code=303)


@router.post("/files/{asset_id}/delete")
def staff_delete_file(
    asset_id: str, hotel_id: str = Depends(require_moderator), db: Client = Depends(get_supabase)
):
    """Delete a file and its record. Pending drafts that named it go on without it."""
    _own_unsent_file(db, hotel_id, asset_id)
    asset_service.delete_asset(db, asset_id)
    return RedirectResponse("/hotel#files", status_code=303)


def _own_draft(db: Client, hotel_id: str, draft_id: str) -> dict:
    """The draft, if it belongs to the staff member's hotel: a URL can't reach another's."""
    draft = content_service.get_draft(db, draft_id)
    if draft.get("hotel_id") != hotel_id:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@router.get("/drafts", name="staff_drafts")
def staff_drafts(
    request: Request,
    member: dict = Depends(require_staff_member),
    db: Client = Depends(get_supabase),
):
    hotel_id = member["hotel_id"]
    pending = content_service.list_drafts(db, hotel_id, "pending_review")
    assets = asset_service.list_assets(db, hotel_id)
    previews, thumbnails = review_images(db, assets, pending)
    return templates.TemplateResponse(
        request,
        "staff/drafts.html",
        {
            "request": request,
            "hotel": hotel_service.get_hotel(db, hotel_id),
            "pending": pending,
            "preview_images": previews,
            "image_choices": image_choices(assets),
            "thumbnails": thumbnails,
            "can_moderate": can_moderate(member),
            "done": request.query_params.get("done"),
        },
    )


@router.post("/drafts/{draft_id}/approve")
def staff_approve(
    draft_id: str, hotel_id: str = Depends(require_moderator), db: Client = Depends(get_supabase)
):
    """As on the dashboard: publish to Buffer through the worker; a second click does nothing."""
    if _own_draft(db, hotel_id, draft_id).get("status") == "pending_review":
        try:
            content_service.approve_draft(db, draft_id)
        except HTTPException as exc:
            if exc.status_code != 404:  # someone else decided it a moment ago
                raise
    return RedirectResponse("/hotel/drafts?done=approved", status_code=303)


@router.post("/drafts/{draft_id}/edit")
def staff_edit(
    draft_id: str,
    body_tr: str = Form(...),
    hotel_id: str = Depends(require_moderator),
    db: Client = Depends(get_supabase),
):
    """As on the dashboard: save a pending draft's edited text, translated again."""
    _own_draft(db, hotel_id, draft_id)
    content_service.edit_draft_text(db, draft_id, body_tr)
    return RedirectResponse(f"/hotel/drafts?done=edited#draft-{draft_id}", status_code=303)


@router.post("/drafts/{draft_id}/images")
def staff_choose_images(
    draft_id: str,
    choice: list[str] = Form([]),
    order: list[str] = Form([]),
    asset_ids: list[str] = Form([]),
    hotel_id: str = Depends(require_moderator),
    db: Client = Depends(get_supabase),
):
    """As on the dashboard: which of the hotel's photos a pending draft carries, in order."""
    _own_draft(db, hotel_id, draft_id)
    choices = image_choices(asset_service.list_assets(db, hotel_id))
    chosen = content_service.chosen_images(choice, order, asset_ids)
    content_service.set_draft_images(db, draft_id, chosen, choices)
    return RedirectResponse(f"/hotel/drafts?done=images#draft-{draft_id}", status_code=303)


@router.post("/drafts/{draft_id}/reject")
def staff_reject(
    draft_id: str,
    feedback: str = Form(""),
    hotel_id: str = Depends(require_moderator),
    db: Client = Depends(get_supabase),
):
    if _own_draft(db, hotel_id, draft_id).get("status") == "pending_review":
        content_service.reject_draft(db, draft_id, feedback.strip() or None)
    return RedirectResponse("/hotel/drafts?done=rejected", status_code=303)


@router.post("/drafts/{draft_id}/delete")
def staff_delete_draft(
    draft_id: str, hotel_id: str = Depends(require_moderator), db: Client = Depends(get_supabase)
):
    """As on the dashboard: delete a draft that isn't at Buffer (409 for one that is)."""
    content_service.delete_draft(db, _own_draft(db, hotel_id, draft_id))
    return RedirectResponse("/hotel/drafts?done=deleted", status_code=303)


def _team_page(request: Request, db: Client, hotel_id: str, user_id: str, **extra: object):
    return templates.TemplateResponse(
        request,
        "staff/team.html",
        {
            "request": request,
            "hotel": hotel_service.get_hotel(db, hotel_id),
            "members": staff_service.list_members(db, hotel_id),
            "invites": list_invites(db, str(request.base_url), hotel_id),
            "me": user_id,
            **extra,
        },
    )


def _other_member(user_id: str, me: str, role: str | None = None) -> None:
    """A hotel admin manages the hotel's other staff: never themselves, so the hotel can't lose
    its admin by a slip (an operator can still change any role), and only to a known role."""
    if user_id == me:
        raise HTTPException(status_code=409, detail="You can't change your own access")
    if role is not None and role not in ROLES:
        raise HTTPException(status_code=422, detail="Unknown staff role")


@router.get("/staff", name="staff_team")
def staff_team(
    request: Request,
    hotel_id: str = Depends(require_hotel_admin),
    user=Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    return _team_page(request, db, hotel_id, user.id)


@router.post("/staff/invite")
def staff_invite(
    request: Request,
    email: str = Form(...),
    role: str = Form(...),
    valid_days: int = Form(7, ge=1, le=30),
    hotel_id: str = Depends(require_hotel_admin),
    user=Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    """As on the dashboard: records an invite for one person in this role, and emails it where
    SMTP is set up."""
    if role not in ROLES:
        raise HTTPException(status_code=422, detail="Unknown staff role")
    status_code, outcome = 200, dict[str, object]()
    if "@" not in email.strip():
        status_code, outcome = 422, {"invite_error": "Bir e-posta adresi girin."}
    else:
        hotel = hotel_service.get_hotel(db, hotel_id)
        link, sent = create_invite(
            db, str(request.base_url), hotel, role, email, valid_days, user.email
        )
        outcome = {"invite_link": link, "invite_email": email.strip().lower(), "invite_sent": sent}
    response = _team_page(request, db, hotel_id, user.id, **outcome)
    response.status_code = status_code
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/staff/{user_id}/role")
def staff_change_role(
    user_id: str,
    role: str = Form(...),
    hotel_id: str = Depends(require_hotel_admin),
    user=Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _other_member(user_id, user.id, role)
    staff_service.set_role(db, hotel_id, user_id, role)
    return RedirectResponse("/hotel/staff?done=role", status_code=303)


@router.post("/staff/{user_id}/remove")
def staff_remove(
    user_id: str,
    hotel_id: str = Depends(require_hotel_admin),
    user=Depends(get_current_user),
    db: Client = Depends(get_supabase),
):
    _other_member(user_id, user.id)
    staff_service.remove_member(db, hotel_id, user_id)
    return RedirectResponse("/hotel/staff?done=removed", status_code=303)


def _details_page(request: Request, hotel: dict, status_code: int = 200, **extra: object):
    return templates.TemplateResponse(
        request,
        "staff/details.html",
        {"request": request, "hotel": hotel, "channels": [c.value for c in SocialChannel], **extra},
        status_code=status_code,
    )


@router.get("/details", name="staff_details")
def staff_details(
    request: Request,
    hotel_id: str = Depends(require_hotel_admin),
    db: Client = Depends(get_supabase),
):
    hotel = hotel_service.get_hotel(db, hotel_id)
    return _details_page(request, hotel, saved=request.query_params.get("done") == "saved")


@router.post("/details")
def staff_save_details(
    request: Request,
    name: str = Form(""),
    location: str = Form(""),
    contact_email: str = Form(""),
    channels: list[str] = Form([]),
    description: str = Form(""),
    hotel_id: str = Depends(require_hotel_admin),
    db: Client = Depends(get_supabase),
):
    """The details a hotel admin keeps up to date. The slug, tier and Buffer profiles stay with
    operators (the dashboard)."""
    form = {"name": name.strip(), "location": location.strip(),
            "contact_email": contact_email.strip(), "description": description.strip()}  # fmt: skip
    try:
        if not (form["name"] and form["location"] and form["contact_email"]):
            raise ValueError("missing")
        payload = HotelUpdate(**form, channels=channels)
    except ValueError:
        hotel = {**hotel_service.get_hotel(db, hotel_id), **form, "channels": channels}
        return _details_page(request, hotel, 422, error=True)
    hotel_service.update_hotel(db, hotel_id, payload)
    return RedirectResponse("/hotel/details?done=saved", status_code=303)
