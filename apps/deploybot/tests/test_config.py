import base64
import binascii

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import Settings

PEM = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,  # BEGIN RSA PRIVATE KEY, as GitHub's
    serialization.NoEncryption(),
)
ENV = {
    "SLACK_APP_TOKEN": "xapp-1",
    "SLACK_BOT_TOKEN": "xoxb-1",
    "SLACK_TEAM_ID": "T1",
    "SLACK_CHANNEL_ID": "C1",
    "GITHUB_APP_CLIENT_ID": "Iv1.x",
    "GITHUB_APP_INSTALLATION_ID": "42",
    "GITHUB_APP_PRIVATE_KEY_BASE64": base64.b64encode(PEM).decode(),
    "ALLOWED_USERS": " U1, U2 ,",
}


def test_settings_come_from_the_environment() -> None:
    settings = Settings.from_env(ENV)
    assert settings.slack_channel_id == "C1"
    assert settings.github_app_private_key == PEM.decode()
    assert settings.allowed_users == {"U1", "U2"}
    assert Settings.from_env({**ENV, "ALLOWED_USERS": ""}).allowed_users == frozenset()
    assert settings.github_repository == "easypeasyops/hotel_social_posts"
    assert Settings.from_env({**ENV, "GITHUB_REPOSITORY": "o/r"}).github_repository == "o/r"


@pytest.mark.parametrize("key", sorted(ENV))
def test_a_missing_setting_fails_at_start(key: str) -> None:
    with pytest.raises(KeyError, match=key):
        Settings.from_env({k: v for k, v in ENV.items() if k != key})


def test_a_key_that_is_not_base64_fails_at_start() -> None:
    with pytest.raises(binascii.Error):
        Settings.from_env({**ENV, "GITHUB_APP_PRIVATE_KEY_BASE64": "-----BEGIN"})


def test_a_key_cut_short_fails_at_start() -> None:
    """As happened: the base64 pasted into .env lost its end, and still began BEGIN RSA."""
    cut = base64.b64encode(PEM[: len(PEM) * 4 // 5]).decode()
    with pytest.raises(ValueError, match="not a whole PEM private key"):
        Settings.from_env({**ENV, "GITHUB_APP_PRIVATE_KEY_BASE64": cut})


# CI's kind e2e loads this for every key (the platform's scripts/kind-e2e.sh).
PLACEHOLDER = "e2e-placeholder"


@pytest.mark.parametrize("offline", [None, "0", "true"])
def test_without_offline_mode_a_placeholder_key_fails_at_start(offline: str | None) -> None:
    env = {**ENV, "GITHUB_APP_PRIVATE_KEY_BASE64": PLACEHOLDER}
    if offline is not None:
        env["DEPLOYBOT_OFFLINE"] = offline
    with pytest.raises(ValueError):  # binascii.Error is one
        Settings.from_env(env)


def test_offline_mode_takes_placeholder_keys_but_not_missing_ones() -> None:
    env = {**{k: PLACEHOLDER for k in ENV}, "DEPLOYBOT_OFFLINE": "1"}
    settings = Settings.from_env(env)
    assert settings.offline
    assert settings.github_app_private_key == ""
    assert not Settings.from_env(ENV).offline
    with pytest.raises(KeyError, match="SLACK_APP_TOKEN"):
        Settings.from_env({k: v for k, v in env.items() if k != "SLACK_APP_TOKEN"})
