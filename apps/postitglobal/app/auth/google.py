"""Sign in with Google, through Supabase Auth's Google provider with PKCE.

/login/google keeps a PKCE verifier in a short-lived cookie and sends the browser to Supabase,
which sends it to Google and back to /auth/callback/google with a one-time code. That code and
the verifier make a Supabase session. Supabase creates no account here (its "Allow new users to
sign up" is off, see the runbook), and only an operator gets a session."""

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from redis.exceptions import RedisError
from supabase_auth.errors import AuthApiError
from supabase_auth.helpers import generate_pkce_challenge, generate_pkce_verifier

from app.auth.dependencies import is_operator
from app.auth.router import NO_ACCESS, _set_session_cookie, templates
from app.auth.sessions import create_session
from app.config import get_settings
from app.database import get_supabase_anon

router = APIRouter()
logger = logging.getLogger(__name__)

VERIFIER_COOKIE = "postitglobal_oauth_verifier"
CALLBACK_PATH = "/auth/callback/google"
VERIFIER_TTL_SECONDS = 10 * 60


def _callback_url() -> str:
    return f"{get_settings().public_base_url.rstrip('/')}{CALLBACK_PATH}"


def _login_error(request: Request, message: str, status_code: int):
    response = templates.TemplateResponse(
        request, "auth/login.html", {"request": request, "error": message}, status_code=status_code
    )
    response.delete_cookie(VERIFIER_COOKIE, path=CALLBACK_PATH, httponly=True)
    return response


@router.get("/login/google", name="google_sign_in")
def start_google_sign_in():
    settings = get_settings()
    if not settings.google_sign_in:
        raise HTTPException(status_code=404)
    verifier = generate_pkce_verifier()
    query = urlencode(
        {
            "provider": "google",
            "redirect_to": _callback_url(),
            "code_challenge": generate_pkce_challenge(verifier),
            "code_challenge_method": "s256",
        }
    )
    response = RedirectResponse(f"{settings.supabase_url}/auth/v1/authorize?{query}", 303)
    # Lax, not Strict: the browser comes back from Google, another site, and must bring it.
    response.set_cookie(
        VERIFIER_COOKIE,
        verifier,
        max_age=VERIFIER_TTL_SECONDS,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path=CALLBACK_PATH,
    )
    return response


@router.get(CALLBACK_PATH)
def finish_google_sign_in(request: Request, code: str | None = None, error_code: str | None = None):
    if error_code == "signup_disabled":
        return _login_error(
            request, "There's no postitglobal account for that Google address.", 403
        )
    verifier = request.cookies.get(VERIFIER_COOKIE)
    if not code or not verifier:
        return _login_error(request, "Google sign-in didn't finish. Try again.", 400)

    try:
        auth_response = get_supabase_anon().auth.exchange_code_for_session(
            {"auth_code": code, "code_verifier": verifier, "redirect_to": _callback_url()}
        )
    except AuthApiError as exc:
        logger.info("Supabase refused a Google sign-in (status=%s, code=%s)", exc.status, exc.code)
        return _login_error(request, "Google sign-in didn't finish. Try again.", 401)
    except Exception:
        logger.exception("Google sign-in exchange failed")
        return _login_error(request, "Sign-in is temporarily unavailable.", 502)

    session = auth_response.session
    if session is None:
        return _login_error(request, "Sign-in did not return a session.", 502)
    if not is_operator(auth_response.user):
        return _login_error(request, NO_ACCESS, 403)
    try:
        session_id = create_session(session.access_token, session.refresh_token, session.expires_at)
    except RedisError:
        return _login_error(request, "Sign-in is temporarily unavailable.", 503)

    # The session cookie is SameSite=Strict, so a redirect in this chain, which began at
    # Google, would arrive without it. A page of ours moves on, and that navigation is ours.
    response = templates.TemplateResponse(
        request, "auth/continue.html", {"request": request, "next": "/dashboard/hotels"}
    )
    _set_session_cookie(response, session_id)
    response.delete_cookie(VERIFIER_COOKIE, path=CALLBACK_PATH, httponly=True)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
