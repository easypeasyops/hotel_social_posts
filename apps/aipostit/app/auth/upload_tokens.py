"""Hotel capabilities: an HMAC-signed token (with SECRET_KEY) naming one hotel, one purpose
and an expiry. The upload link is one; any other purpose is a different token."""

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime

from app.config import get_settings
from app.hotels.staff import ROLES

UPLOAD_PURPOSE = "hotel-media-upload"
UPLOAD_TOKEN_TTL_SECONDS = 24 * 60 * 60
# A hotel's staff invite: anyone with it can make a staff account for that hotel (/signup).
STAFF_INVITE_PURPOSE = "staff-invite"
STAFF_INVITE_TTL_SECONDS = 7 * 24 * 60 * 60
# A recorded staff invite: points at its staff_invites row, which says who may use it and how.
STAFF_INVITE_RECORD_PURPOSE = "staff-invite-record"


def staff_invite_purpose(role: str) -> str:
    """Each role's invite is its own purpose. A hotel admin's is the purpose invites had before
    roles, so links sent then still make hotel admins, as they did."""
    return STAFF_INVITE_PURPOSE if role == "hotel_admin" else f"{STAFF_INVITE_PURPOSE}:{role}"


def read_staff_invite(token: str) -> tuple[str, str, str | None] | None:
    """The hotel, role and email (None: anyone with the link) a valid staff invite names, or
    None."""
    for role in ROLES:
        payload = read_token_payload(token, staff_invite_purpose(role))
        if payload is not None:
            return payload["hotel_id"], role, payload.get("email")
    return None


def create_recorded_invite_token(
    hotel_id: str, invite_id: str, email: str, expires_at: datetime
) -> str:
    """The link token for a staff_invites row, expiring with the row. The email is there for
    the sign-up page to show; /signup checks the row's."""
    ttl_seconds = int((expires_at - datetime.now(UTC)).total_seconds())
    return create_token(
        hotel_id, STAFF_INVITE_RECORD_PURPOSE, ttl_seconds, email, invite_id=invite_id
    )


def read_recorded_invite(token: str) -> tuple[str, str] | None:
    """The hotel and staff_invites row id a valid recorded-invite token names, or None."""
    payload = read_token_payload(token, STAFF_INVITE_RECORD_PURPOSE)
    if payload is None or not isinstance(payload.get("invite_id"), str):
        return None
    return payload["hotel_id"], payload["invite_id"]


def _sign(encoded_payload: str) -> bytes:
    return hmac.new(
        get_settings().secret_key.encode(), encoded_payload.encode(), hashlib.sha256
    ).digest()


def create_token(
    hotel_id: str,
    purpose: str,
    ttl_seconds: int,
    email: str | None = None,
    invite_id: str | None = None,
) -> str:
    """A token for this hotel and purpose; with an email, one that person alone may use (a
    staff invite sent to them); with an invite_id, one that points at a staff_invites row.
    Both are signed with the rest, so they can't be changed."""
    payload: dict[str, str | int] = {
        "hotel_id": hotel_id,
        "purpose": purpose,
        "expires_at": int(time.time()) + ttl_seconds,
        "nonce": secrets.token_urlsafe(12),
    }
    if email is not None:
        payload["email"] = email.strip().lower()
    if invite_id is not None:
        payload["invite_id"] = invite_id
    encoded_payload = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    encoded_signature = base64.urlsafe_b64encode(_sign(encoded_payload)).rstrip(b"=").decode()
    return f"{encoded_payload}.{encoded_signature}"


def read_token(token: str, purpose: str) -> str | None:
    """The hotel a valid, unexpired token for this purpose names; None for any other token."""
    payload = read_token_payload(token, purpose)
    return payload["hotel_id"] if payload else None


def read_token_payload(token: str, purpose: str) -> dict | None:
    """What a valid, unexpired token for this purpose says (hotel_id, and email if it names
    one); None for any other token."""
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        supplied_signature = base64.urlsafe_b64decode(
            encoded_signature + "=" * (-len(encoded_signature) % 4)
        )
        if not hmac.compare_digest(_sign(encoded_payload), supplied_signature):
            return None

        payload_bytes = base64.urlsafe_b64decode(
            encoded_payload + "=" * (-len(encoded_payload) % 4)
        )
        payload = json.loads(payload_bytes)
        if (
            payload.get("purpose") == purpose
            and isinstance(payload.get("hotel_id"), str)
            and isinstance(payload.get("expires_at"), int)
            and payload["expires_at"] > int(time.time())
            and isinstance(payload.get("email", ""), str)
        ):
            return payload
        return None
    except ValueError, TypeError, json.JSONDecodeError:
        return None


def create_upload_token(hotel_id: str) -> str:
    return create_token(hotel_id, UPLOAD_PURPOSE, UPLOAD_TOKEN_TTL_SECONDS)


def verify_upload_token(token: str, hotel_id: str) -> bool:
    return read_token(token, UPLOAD_PURPOSE) == hotel_id
