import time

from fastapi import Depends, Header, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase_auth.errors import AuthApiError

from app.account import menu
from app.auth.sessions import (
    SESSION_COOKIE,
    RedisError,
    get_session,
    update_session,
)
from app.auth.upload_tokens import verify_upload_token
from app.config import get_settings
from app.database import get_supabase, get_supabase_anon
from app.hotels.staff import can_moderate, hotel_of, member_of

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> dict:
    """
    Validates a Supabase bearer token or the browser's Redis-backed session.
    """
    auth = get_supabase_anon().auth
    if credentials is not None:
        access_token = credentials.credentials
    else:
        session_id = request.cookies.get(SESSION_COOKIE)
        if not session_id:
            raise HTTPException(status_code=401, detail="Authentication required")

        try:
            session = get_session(session_id)
        except RedisError as exc:
            raise HTTPException(status_code=503, detail="Session store unavailable") from exc

        if not session:
            raise HTTPException(status_code=401, detail="Session expired")

        access_token = session["access_token"]
        if session.get("expires_at") and session["expires_at"] <= int(time.time()) + 60:
            try:
                refreshed = auth.refresh_session(session["refresh_token"]).session
            except AuthApiError as exc:
                raise HTTPException(status_code=401, detail="Session expired") from exc
            except Exception as exc:
                raise HTTPException(
                    status_code=502, detail="Authentication service unavailable"
                ) from exc
            if refreshed is None:
                raise HTTPException(status_code=401, detail="Session expired")
            access_token = refreshed.access_token
            try:
                update_session(
                    session_id,
                    refreshed.access_token,
                    refreshed.refresh_token,
                    refreshed.expires_at,
                )
            except RedisError as exc:
                raise HTTPException(status_code=503, detail="Session store unavailable") from exc

    try:
        response = auth.get_user(access_token)
    except AuthApiError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Authentication service unavailable") from exc
    if response.user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return response.user


def is_operator(user) -> bool:
    """Operators are marked by hand in Supabase: app_metadata.role = "operator". Users can't
    edit their own app_metadata, so a self-made account never passes this."""
    return (user.app_metadata or {}).get("role") == "operator"


def require_operator(request: Request, user=Depends(get_current_user)):
    """The dashboard and the operator API: a signed-in account without the operator role is
    refused (403), not sent to sign in again. Pages read the user menu from request.state."""
    if not is_operator(user):
        raise HTTPException(status_code=403, detail="This account has no operator access")
    request.state.account = menu(user)
    return user


def landing_page(user) -> str | None:
    """Where a new session starts: the dashboard for an operator, the hotel's own pages for
    its staff; None for an account with no access, which then gets no session."""
    if is_operator(user):
        return "/dashboard/hotels"
    if hotel_of(get_supabase(), user.id):
        return "/hotel"
    return None


def require_staff_member(
    request: Request, user=Depends(get_current_user), db=Depends(get_supabase)
) -> dict:
    """The staff pages: this account's hotel and role (member_of); 403 for anyone else. Pages
    read the user menu from request.state."""
    member = member_of(db, user.id)
    if member is None:
        raise HTTPException(status_code=403, detail="This account is not hotel staff")
    request.state.account = menu(user, member)
    return member


def require_staff(member: dict = Depends(require_staff_member)) -> str:
    """The hotel this staff account works for, whatever its role."""
    return member["hotel_id"]


def require_moderator(member: dict = Depends(require_staff_member)) -> str:
    """The hotel, for a staff account that may change and decide its content (can_moderate);
    403 for a content creator."""
    if not can_moderate(member):
        raise HTTPException(status_code=403, detail="This account can only upload content")
    return member["hotel_id"]


def require_hotel_admin(member: dict = Depends(require_staff_member)) -> str:
    """The hotel, for its hotel admin (who manages its staff); 403 for any other role."""
    if member["role"] != "hotel_admin":
        raise HTTPException(status_code=403, detail="This account is not the hotel's admin")
    return member["hotel_id"]


def signed_in_landing_page(request: Request) -> str | None:
    """Where this browser's signed-in account belongs (landing_page), or None: no session, an
    expired one, or an account with no access. For pages anyone can open, such as the home page."""
    if not request.cookies.get(SESSION_COOKIE):
        return None
    try:
        user = get_current_user(request, None)
    except HTTPException:
        return None
    return landing_page(user)


def verify_hotel_upload_token(
    hotel_id: str,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> None:
    """Authorize a short-lived upload capability for the matching hotel."""
    if credentials is None or not verify_upload_token(credentials.credentials, hotel_id):
        raise HTTPException(status_code=403, detail="Invalid or expired upload link")


def verify_cron_secret(x_cron_secret: str = Header(...)):
    """
    Protects the /internal/* job triggers: the caller passes the secret in the
    X-Cron-Secret header.
    """
    settings = get_settings()
    if x_cron_secret != settings.cron_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
