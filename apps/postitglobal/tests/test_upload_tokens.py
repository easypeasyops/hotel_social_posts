"""Upload links: an HMAC-signed token per hotel that expires after a day."""

import time

import pytest

from app.auth import upload_tokens
from app.auth.upload_tokens import create_upload_token, verify_upload_token


def test_a_token_opens_its_own_hotel_only() -> None:
    token = create_upload_token("hotel-1")
    assert verify_upload_token(token, "hotel-1")
    assert not verify_upload_token(token, "hotel-2")


def test_a_tampered_token_is_refused() -> None:
    payload, signature = create_upload_token("hotel-1").split(".")
    other_payload, _ = create_upload_token("hotel-2").split(".")
    assert not verify_upload_token(f"{other_payload}.{signature}", "hotel-2")
    assert not verify_upload_token(f"{payload}.{signature[:-2]}AA", "hotel-1")


@pytest.mark.parametrize("token", ["", "no-dot", "a.b.c", "!!!.???"])
def test_a_malformed_token_is_refused(token: str) -> None:
    assert not verify_upload_token(token, "hotel-1")


def test_a_token_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    token = create_upload_token("hotel-1")
    later = time.time() + upload_tokens.UPLOAD_TOKEN_TTL_SECONDS + 1
    monkeypatch.setattr(upload_tokens.time, "time", lambda: later)
    assert not verify_upload_token(token, "hotel-1")


def test_a_token_from_another_secret_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    token = create_upload_token("hotel-1")
    monkeypatch.setenv("SECRET_KEY", "another-secret")
    get_settings.cache_clear()
    assert not verify_upload_token(token, "hotel-1")
