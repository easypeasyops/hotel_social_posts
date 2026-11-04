from fastapi import APIRouter, Depends

from app.auth.dependencies import require_operator
from app.content import service
from app.content.models import ReviewAction
from app.database import get_supabase
from supabase import Client

router = APIRouter()


@router.get("/hotel/{hotel_id}/drafts")
def list_drafts(
    hotel_id: str,
    status: str = "pending_review",
    db: Client = Depends(get_supabase),
    _user=Depends(require_operator),
):
    return service.list_drafts(db, hotel_id, status)


@router.get("/drafts/{draft_id}")
def get_draft(
    draft_id: str,
    db: Client = Depends(get_supabase),
    _user=Depends(require_operator),
):
    return service.get_draft(db, draft_id)


@router.patch("/drafts/{draft_id}/approve")
def approve_draft(
    draft_id: str,
    db: Client = Depends(get_supabase),
    _user=Depends(require_operator),
):
    return service.approve_draft(db, draft_id)


@router.patch("/drafts/{draft_id}/reject")
def reject_draft(
    draft_id: str,
    action: ReviewAction,
    db: Client = Depends(get_supabase),
    _user=Depends(require_operator),
):
    return service.reject_draft(db, draft_id, action.feedback)


@router.get("/drafts/{draft_id}/translations")
def get_translations(
    draft_id: str,
    db: Client = Depends(get_supabase),
    _user=Depends(require_operator),
):
    return service.get_translations(db, draft_id)
