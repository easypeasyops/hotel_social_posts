"""deploybot's settings, from its environment: in the cluster the keys come from the
platform's `deploybot` store and the rest from deploy/envs/ (RUNBOOK)."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    slack_app_token: str  # xapp-…: opens the Socket Mode connection
    slack_bot_token: str  # xoxb-…
    slack_team_id: str  # our workspace: commands from any other are refused
    slack_channel_id: str  # #aipostit-deploys: the only channel that takes commands
    github_app_client_id: str  # the deploybot GitHub App (not the release app)
    github_app_installation_id: str  # its installation on the repository
    github_app_private_key: str  # PEM
    github_repository: str = "easypeasyops/hotel_social_posts"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        """Every setting is required but the repository; a missing one fails at start."""
        return cls(
            slack_app_token=env["SLACK_APP_TOKEN"],
            slack_bot_token=env["SLACK_BOT_TOKEN"],
            slack_team_id=env["SLACK_TEAM_ID"],
            slack_channel_id=env["SLACK_CHANNEL_ID"],
            github_app_client_id=env["GITHUB_APP_CLIENT_ID"],
            github_app_installation_id=env["GITHUB_APP_INSTALLATION_ID"],
            github_app_private_key=env["GITHUB_APP_PRIVATE_KEY"],
            github_repository=env.get("GITHUB_REPOSITORY", cls.github_repository),
        )
