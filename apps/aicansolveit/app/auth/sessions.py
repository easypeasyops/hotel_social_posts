import json
import secrets
from functools import lru_cache

from redis import Redis
from redis.exceptions import RedisError

from app.config import get_settings

SESSION_COOKIE = "aicansolveit_session"
PASSWORD_RESET_COOKIE = "aicansolveit_password_reset"  # noqa: S105
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
PASSWORD_RESET_TTL_SECONDS = 15 * 60


@lru_cache
def get_session_store() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


def create_session(access_token: str, refresh_token: str, expires_at: int | None) -> str:
    session_id = secrets.token_urlsafe(32)
    session_data = json.dumps(
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
        }
    )
    get_session_store().setex(f"web-session:{session_id}", SESSION_TTL_SECONDS, session_data)
    return session_id


def get_session(session_id: str) -> dict | None:
    value = get_session_store().get(f"web-session:{session_id}")
    return json.loads(value) if value else None


def update_session(
    session_id: str, access_token: str, refresh_token: str, expires_at: int | None
) -> None:
    session_data = json.dumps(
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
        }
    )
    get_session_store().setex(f"web-session:{session_id}", SESSION_TTL_SECONDS, session_data)


def delete_session(session_id: str) -> None:
    get_session_store().delete(f"web-session:{session_id}")


def create_password_reset_session(
    access_token: str, refresh_token: str, expires_at: int | None
) -> str:
    reset_id = secrets.token_urlsafe(32)
    session_data = json.dumps(
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
        }
    )
    get_session_store().setex(
        f"password-reset:{reset_id}", PASSWORD_RESET_TTL_SECONDS, session_data
    )
    return reset_id


def get_password_reset_session(reset_id: str) -> dict | None:
    value = get_session_store().get(f"password-reset:{reset_id}")
    return json.loads(value) if value else None


def delete_password_reset_session(reset_id: str) -> None:
    get_session_store().delete(f"password-reset:{reset_id}")


__all__ = [
    "PASSWORD_RESET_COOKIE",
    "PASSWORD_RESET_TTL_SECONDS",
    "RedisError",
    "SESSION_COOKIE",
    "SESSION_TTL_SECONDS",
    "create_session",
    "create_password_reset_session",
    "delete_session",
    "delete_password_reset_session",
    "get_session",
    "get_password_reset_session",
    "update_session",
]
