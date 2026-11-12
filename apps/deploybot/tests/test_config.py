import pytest

from app.config import Settings

ENV = {
    "SLACK_APP_TOKEN": "xapp-1",
    "SLACK_BOT_TOKEN": "xoxb-1",
    "SLACK_TEAM_ID": "T1",
    "SLACK_CHANNEL_ID": "C1",
}


def test_settings_come_from_the_environment() -> None:
    settings = Settings.from_env(ENV)
    assert settings.slack_channel_id == "C1"


@pytest.mark.parametrize("key", sorted(ENV))
def test_a_missing_setting_fails_at_start(key: str) -> None:
    with pytest.raises(KeyError, match=key):
        Settings.from_env({k: v for k, v in ENV.items() if k != key})
