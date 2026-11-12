import pytest

from app.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        slack_app_token="xapp-test",
        slack_bot_token="xoxb-test",
        slack_team_id="T1",
        slack_channel_id="C1",
        github_app_client_id="Iv1.test",
        github_app_installation_id="42",
        github_app_private_key="unused",
    )
