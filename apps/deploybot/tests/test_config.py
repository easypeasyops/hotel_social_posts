import base64
import binascii

import pytest

from app.config import Settings

ENV = {
    "SLACK_APP_TOKEN": "xapp-1",
    "SLACK_BOT_TOKEN": "xoxb-1",
    "SLACK_TEAM_ID": "T1",
    "SLACK_CHANNEL_ID": "C1",
    "GITHUB_APP_CLIENT_ID": "Iv1.x",
    "GITHUB_APP_INSTALLATION_ID": "42",
    "GITHUB_APP_PRIVATE_KEY_BASE64": base64.b64encode(b"-----BEGIN PRIVATE KEY-----\nk\n").decode(),
    "ALLOWED_USERS": " U1, U2 ,",
}


def test_settings_come_from_the_environment() -> None:
    settings = Settings.from_env(ENV)
    assert settings.slack_channel_id == "C1"
    assert settings.github_app_private_key == "-----BEGIN PRIVATE KEY-----\nk\n"
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
