"""deploybot's settings, from its environment: in the cluster the keys come from the
platform's `deploybot` store and the rest from deploy/envs/ (RUNBOOK)."""

import base64
from collections.abc import Mapping
from dataclasses import dataclass

from cryptography.hazmat.primitives.serialization import load_pem_private_key


@dataclass(frozen=True)
class Settings:
    slack_app_token: str  # xapp-…: opens the Socket Mode connection
    slack_bot_token: str  # xoxb-…
    slack_team_id: str  # our workspace: commands from any other are refused
    slack_channel_id: str  # #aipostit-deploys: the only channel that takes commands
    github_app_client_id: str  # the deploybot GitHub App (not the release app)
    github_app_installation_id: str  # its installation on the repository
    github_app_private_key: str  # PEM
    allowed_users: frozenset[str]  # Slack user IDs that may release, promote and roll back
    github_repository: str = "easypeasyops/hotel_social_posts"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        """Every setting is required but the repository; a missing or bad one fails at start."""
        return cls(
            slack_app_token=env["SLACK_APP_TOKEN"],
            slack_bot_token=env["SLACK_BOT_TOKEN"],
            slack_team_id=env["SLACK_TEAM_ID"],
            slack_channel_id=env["SLACK_CHANNEL_ID"],
            github_app_client_id=env["GITHUB_APP_CLIENT_ID"],
            github_app_installation_id=env["GITHUB_APP_INSTALLATION_ID"],
            github_app_private_key=_private_key(env["GITHUB_APP_PRIVATE_KEY_BASE64"]),
            # Comma-separated; empty means no one may.
            allowed_users=frozenset(
                u.strip() for u in env["ALLOWED_USERS"].split(",") if u.strip()
            ),
            github_repository=env.get("GITHUB_REPOSITORY", cls.github_repository),
        )


def _private_key(encoded: str) -> str:
    """The PEM key from its base64 (one line: the platform's store loads a dotenv file, one
    line a key), checked now: a key cut short in the paste fails at start, not at the first
    command."""
    pem = base64.b64decode(encoded, validate=True)
    try:
        load_pem_private_key(pem, password=None)
    except ValueError as error:
        raise ValueError("GITHUB_APP_PRIVATE_KEY_BASE64 is not a whole PEM private key") from error
    return pem.decode()
