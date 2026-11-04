"""Hotel capabilities: an HMAC-signed token (with SECRET_KEY) naming one hotel, one purpose
and an expiry. The upload link is one; any other purpose is a different token."""

import base64
import hashlib
import hmac
import json
import secrets
import time

from app.config import get_settings

UPLOAD_PURPOSE = "hotel-media-upload"
UPLOAD_TOKEN_TTL_SECONDS = 24 * 60 * 60


def _sign(encoded_payload: str) -> bytes:
    return hmac.new(
        get_settings().secret_key.encode(), encoded_payload.encode(), hashlib.sha256
    ).digest()


def create_token(hotel_id: str, purpose: str, ttl_seconds: int) -> str:
    payload = {
        "hotel_id": hotel_id,
        "purpose": purpose,
        "expires_at": int(time.time()) + ttl_seconds,
        "nonce": secrets.token_urlsafe(12),
    }
    encoded_payload = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    encoded_signature = base64.urlsafe_b64encode(_sign(encoded_payload)).rstrip(b"=").decode()
    return f"{encoded_payload}.{encoded_signature}"


def read_token(token: str, purpose: str) -> str | None:
    """The hotel a valid, unexpired token for this purpose names; None for any other token."""
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
        ):
            return payload["hotel_id"]
        return None
    except ValueError, TypeError, json.JSONDecodeError:
        return None


def create_upload_token(hotel_id: str) -> str:
    return create_token(hotel_id, UPLOAD_PURPOSE, UPLOAD_TOKEN_TTL_SECONDS)


def verify_upload_token(token: str, hotel_id: str) -> bool:
    return read_token(token, UPLOAD_PURPOSE) == hotel_id
