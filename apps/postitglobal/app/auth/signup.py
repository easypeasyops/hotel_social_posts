"""Hotel staff sign-up, only from an invite link (/signup#invite=…): a signed, 7-day
capability for one hotel and role (staff_invite_purpose), and for one email when it was sent
to one person. The account is made with the service role (Supabase's own sign-up stays off),
tied to that hotel in hotel_members, and signed in."""

import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from redis.exceptions import RedisError
from supabase_auth.errors import AuthApiError

from app.auth.router import _set_session_cookie, templates
from app.auth.sessions import create_session
from app.auth.upload_tokens import read_staff_invite
from app.database import get_supabase, get_supabase_anon

router = APIRouter()
logger = logging.getLogger(__name__)

INVALID_INVITE = (
    "This invite link is invalid or has expired. Ask your postitglobal contact for a new one."
)


def _page(request: Request, status_code: int = 200, **context):
    response = templates.TemplateResponse(
        request, "auth/signup.html", {"request": request, **context}, status_code=status_code
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/signup", name="signup_page")
def signup_page(request: Request):
    return _page(request)


@router.post("/signup")
def sign_up(
    request: Request,
    invite: str = Form(""),
    email: str = Form(...),
    password: str = Form(...),
    password_confirmation: str = Form(...),
):
    invited = read_staff_invite(invite)
    if invited is None:
        return _page(request, 400, invite_error=INVALID_INVITE)
    hotel_id, role, invited_email = invited
    form = {"invite": invite, "email": email}
    if invited_email is not None and email.strip().lower() != invited_email:
        # An invite sent to one person: only the address it was sent to signs up with it.
        return _page(request, 403, error=f"This invite is for {invited_email}.", **form)
    if len(password) < 8:
        return _page(request, 422, error="Password must be at least 8 characters.", **form)
    if password != password_confirmation:
        return _page(request, 422, error="The passwords do not match.", **form)

    db = get_supabase()
    if not db.table("hotels").select("id").eq("id", hotel_id).execute().data:
        return _page(request, 400, invite_error=INVALID_INVITE)

    try:
        # Confirmed at once: the invite, not the inbox, is what vouches for this person.
        created = db.auth.admin.create_user(
            {"email": email, "password": password, "email_confirm": True}
        )
    except AuthApiError as exc:
        logger.info("Supabase refused a staff sign-up (status=%s, code=%s)", exc.status, exc.code)
        if exc.code == "email_exists":
            return _page(request, 409, error="An account with this email already exists.", **form)
        if exc.code == "weak_password":
            return _page(request, 422, error="Choose a stronger password.", **form)
        return _page(request, 400, error="Could not create the account.", **form)
    except Exception:
        logger.exception("Staff sign-up failed")
        return _page(request, 502, error="Sign-up is temporarily unavailable.", **form)

    user = created.user
    try:
        db.table("hotel_members").insert(
            {"user_id": user.id, "hotel_id": hotel_id, "email": user.email or email, "role": role}
        ).execute()
    except Exception:
        logger.exception("Staff sign-up could not record the hotel; removing the new account")
        db.auth.admin.delete_user(user.id)
        return _page(request, 502, error="Sign-up is temporarily unavailable.", **form)

    # The account exists now; if signing it in fails, the sign-in page takes it from here.
    signed_up = RedirectResponse("/login?signup=done", status_code=303)
    try:
        session = (
            get_supabase_anon()
            .auth.sign_in_with_password({"email": email, "password": password})
            .session
        )
    except Exception:
        logger.exception("Staff account created but its first sign-in failed")
        return signed_up
    if session is None:
        return signed_up
    try:
        session_id = create_session(session.access_token, session.refresh_token, session.expires_at)
    except RedisError:
        return signed_up

    response = RedirectResponse("/hotel", status_code=303)
    _set_session_cookie(response, session_id)
    return response
