import time

from fastapi import HTTPException, Security, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase_auth.errors import AuthApiError
from app.database import get_supabase_anon
from app.config import get_settings
from app.auth.sessions import (
    SESSION_COOKIE,
    RedisError,
    get_session,
    update_session,
)
from app.auth.upload_tokens import verify_upload_token

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
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
                raise HTTPException(status_code=502, detail="Authentication service unavailable") from exc
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


async def verify_hotel_upload_token(
    hotel_id: str,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> None:
    """Authorize a short-lived upload capability for the matching hotel."""
    if credentials is None or not verify_upload_token(credentials.credentials, hotel_id):
        raise HTTPException(status_code=403, detail="Invalid or expired upload link")


async def verify_cron_secret(x_cron_secret: str = Header(...)):
    """
    Protects /internal/* endpoints called by Railway cron.
    Railway cron passes the secret in X-Cron-Secret header.
    """
    settings = get_settings()
    if x_cron_secret != settings.cron_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
