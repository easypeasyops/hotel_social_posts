import base64
import hashlib
import hmac
import json
import secrets
import time

from app.config import get_settings

UPLOAD_TOKEN_TTL_SECONDS = 24 * 60 * 60


def create_upload_token(hotel_id: str) -> str:
    payload = {
        "hotel_id": hotel_id,
        "purpose": "hotel-media-upload",
        "expires_at": int(time.time()) + UPLOAD_TOKEN_TTL_SECONDS,
        "nonce": secrets.token_urlsafe(12),
    }
    encoded_payload = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    signature = hmac.new(
        get_settings().secret_key.encode(),
        encoded_payload.encode(),
        hashlib.sha256,
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{encoded_payload}.{encoded_signature}"


def verify_upload_token(token: str, hotel_id: str) -> bool:
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        expected_signature = hmac.new(
            get_settings().secret_key.encode(),
            encoded_payload.encode(),
            hashlib.sha256,
        ).digest()
        supplied_signature = base64.urlsafe_b64decode(
            encoded_signature + "=" * (-len(encoded_signature) % 4)
        )
        if not hmac.compare_digest(expected_signature, supplied_signature):
            return False

        payload_bytes = base64.urlsafe_b64decode(
            encoded_payload + "=" * (-len(encoded_payload) % 4)
        )
        payload = json.loads(payload_bytes)
        return (
            payload.get("hotel_id") == hotel_id
            and payload.get("purpose") == "hotel-media-upload"
            and isinstance(payload.get("expires_at"), int)
            and payload["expires_at"] > int(time.time())
        )
    except (ValueError, TypeError, json.JSONDecodeError):
        return False
