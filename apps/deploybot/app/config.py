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

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        """Every setting is required; a missing one fails at start."""
        return cls(
            slack_app_token=env["SLACK_APP_TOKEN"],
            slack_bot_token=env["SLACK_BOT_TOKEN"],
            slack_team_id=env["SLACK_TEAM_ID"],
            slack_channel_id=env["SLACK_CHANNEL_ID"],
        )
