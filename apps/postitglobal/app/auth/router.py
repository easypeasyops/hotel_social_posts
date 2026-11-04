import logging  # noqa: I001

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from redis.exceptions import RedisError
from supabase_auth.errors import AuthApiError
from supabase import create_client

from app.auth.dependencies import landing_page
from app.auth.sessions import (
    PASSWORD_RESET_COOKIE,
    PASSWORD_RESET_TTL_SECONDS,
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    create_password_reset_session,
    create_session,
    delete_session,
    delete_password_reset_session,
    get_password_reset_session,
)
from app.config import get_settings
from app.database import get_supabase_anon

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["google_sign_in"] = lambda: get_settings().google_sign_in
logger = logging.getLogger(__name__)

NO_ACCESS = "This account doesn't have access to postitglobal."


class CallbackTokens(BaseModel):
    """What the callback page posts from a password-recovery link's URL fragment."""

    access_token: str
    refresh_token: str
    expires_at: int | None = None
    flow_type: str


def _set_session_cookie(response, session_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=get_settings().session_cookie_secure,
        samesite="strict",
        path="/",
    )


@router.get("/login", name="login_page")
def login_page(request: Request):
    return templates.TemplateResponse(request, "auth/login.html", {"request": request})


@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    try:
        auth_response = get_supabase_anon().auth.sign_in_with_password(
            {"email": email, "password": password}
        )
    except AuthApiError:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"request": request, "error": "Email or password is incorrect."},
            status_code=401,
        )
    except Exception:
        logger.exception("Password sign-in failed")
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"request": request, "error": "Sign-in is temporarily unavailable."},
            status_code=502,
        )

    session = auth_response.session
    if session is None:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"request": request, "error": "Sign-in did not return a session."},
            status_code=502,
        )
    next_page = landing_page(auth_response.user)
    if next_page is None:
        return templates.TemplateResponse(
            request, "auth/login.html", {"request": request, "error": NO_ACCESS}, status_code=403
        )

    try:
        session_id = create_session(session.access_token, session.refresh_token, session.expires_at)
    except RedisError:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"request": request, "error": "Sign-in is temporarily unavailable."},
            status_code=503,
        )

    response = RedirectResponse(next_page, status_code=303)
    _set_session_cookie(response, session_id)
    return response


@router.get("/forgot-password", name="forgot_password_page")
def forgot_password_page(request: Request):
    return templates.TemplateResponse(request, "auth/forgot_password.html", {"request": request})


@router.post("/forgot-password")
def request_password_reset(request: Request, email: str = Form(...)):
    settings = get_settings()
    callback_url = f"{settings.public_base_url.rstrip('/')}/auth/callback"

    try:
        get_supabase_anon().auth.reset_password_for_email(
            email,
            options={"redirect_to": callback_url},
        )
    except AuthApiError as exc:
        logger.info(
            "Supabase declined a password-reset request (status=%s, code=%s)",
            exc.status,
            exc.code,
        )
    except Exception:
        logger.exception("Password-reset email request failed")
        return templates.TemplateResponse(
            request,
            "auth/forgot_password.html",
            {
                "request": request,
                "error": "Could not send a reset link right now. Try again later.",
            },
            status_code=502,
        )

    return templates.TemplateResponse(
        request, "auth/forgot_password.html", {"request": request, "sent_to": email}
    )


@router.get("/auth/callback", name="auth_callback")
def auth_callback(request: Request):
    response = templates.TemplateResponse(request, "auth/callback.html", {"request": request})
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.post("/auth/callback/recovery")
def start_password_reset(payload: CallbackTokens):
    if payload.flow_type != "recovery":
        raise HTTPException(status_code=400, detail="This is not a password reset link")

    try:
        user_response = get_supabase_anon().auth.get_user(payload.access_token)
    except AuthApiError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired reset link") from exc
    except Exception as exc:
        logger.exception("Password-reset token validation failed")
        raise HTTPException(status_code=502, detail="Authentication service unavailable") from exc

    if user_response.user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired reset link")

    try:
        reset_id = create_password_reset_session(
            payload.access_token, payload.refresh_token, payload.expires_at
        )
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Session store unavailable") from exc

    response = RedirectResponse("/reset-password", status_code=303)
    response.set_cookie(
        PASSWORD_RESET_COOKIE,
        reset_id,
        max_age=PASSWORD_RESET_TTL_SECONDS,
        httponly=True,
        secure=get_settings().session_cookie_secure,
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/reset-password", name="reset_password_page")
def reset_password_page(request: Request):
    reset_id = request.cookies.get(PASSWORD_RESET_COOKIE)
    if not reset_id:
        return RedirectResponse("/login?error=reset", status_code=303)

    try:
        reset_session = get_password_reset_session(reset_id)
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Session store unavailable") from exc
    if not reset_session:
        response = RedirectResponse("/login?error=reset", status_code=303)
        response.delete_cookie(PASSWORD_RESET_COOKIE, path="/", httponly=True)
        return response

    response = templates.TemplateResponse(request, "auth/reset_password.html", {"request": request})
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.post("/reset-password")
def update_password(
    request: Request,
    password: str = Form(...),
    password_confirmation: str = Form(...),
):
    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "auth/reset_password.html",
            {"request": request, "error": "Password must be at least 8 characters."},
            status_code=422,
        )
    if password != password_confirmation:
        return templates.TemplateResponse(
            request,
            "auth/reset_password.html",
            {"request": request, "error": "The passwords do not match."},
            status_code=422,
        )

    reset_id = request.cookies.get(PASSWORD_RESET_COOKIE)
    if not reset_id:
        return RedirectResponse("/login?error=reset", status_code=303)

    try:
        reset_session = get_password_reset_session(reset_id)
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Session store unavailable") from exc
    if not reset_session:
        response = RedirectResponse("/login?error=reset", status_code=303)
        response.delete_cookie(PASSWORD_RESET_COOKIE, path="/", httponly=True)
        return response

    settings = get_settings()
    auth_client = create_client(settings.supabase_url, settings.supabase_anon_key)
    auth = auth_client.auth
    try:
        auth.set_session(
            reset_session["access_token"],
            reset_session["refresh_token"],
        )
        auth.update_user({"password": password})
        session = auth.get_session()
        # The password changed either way; only an account with access is signed in.
        next_page = landing_page(session.user) if session else None
        if next_page is None:
            delete_password_reset_session(reset_id)
            response = templates.TemplateResponse(
                request,
                "auth/reset_password.html",
                {
                    "request": request,
                    "success": "Password updated. Sign in with your new password.",
                },
                status_code=200,
            )
            response.delete_cookie(PASSWORD_RESET_COOKIE, path="/", httponly=True)
            response.headers["Cache-Control"] = "no-store"
            return response
    except AuthApiError as exc:
        logger.info("Supabase rejected password reset (status=%s, code=%s)", exc.status, exc.code)
        return templates.TemplateResponse(
            request,
            "auth/reset_password.html",
            {
                "request": request,
                "error": "Could not update the password. The reset link may have expired, or the password may not meet project requirements.",  # noqa: E501
            },
            status_code=400,
        )
    except Exception as exc:  # noqa: F841
        logger.exception("Password update failed")
        return templates.TemplateResponse(
            request,
            "auth/reset_password.html",
            {
                "request": request,
                "error": "Could not update your password right now. Please try again.",
            },
            status_code=502,
        )

    try:
        delete_password_reset_session(reset_id)
        session_id = create_session(session.access_token, session.refresh_token, session.expires_at)
    except RedisError as exc:
        raise HTTPException(
            status_code=503, detail="Password changed, but session creation failed; sign in again"
        ) from exc

    response = RedirectResponse(next_page, status_code=303)
    response.delete_cookie(PASSWORD_RESET_COOKIE, path="/", httponly=True)
    _set_session_cookie(response, session_id)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/logout")
def logout(request: Request):
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        try:
            delete_session(session_id)
        except RedisError:
            response = RedirectResponse("/login?error=session", status_code=303)
            response.delete_cookie(SESSION_COOKIE, path="/", httponly=True)
            return response

    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True)
    return response
