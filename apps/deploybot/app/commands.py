"""What `/aipostit <text>` does: who may run it, and the reply. Slack-free, so it is tested
without Slack; app/main.py hands it each command."""

import logging
from dataclasses import dataclass

from app.config import Settings

log = logging.getLogger(__name__)

HELP = (
    "deploybot is connected. Its commands (`status`, `release`, `promote`, `rollback`) come next."
)


@dataclass(frozen=True)
class Reply:
    text: str
    public: bool  # in the channel for everyone, or only to the person who asked


def handle(text: str, *, user_id: str, channel_id: str, team_id: str, settings: Settings) -> Reply:
    # In #aipostit-deploys only, so everyone there sees every command.
    if team_id != settings.slack_team_id or channel_id != settings.slack_channel_id:
        log.warning("refused %s: /aipostit %r outside the channel (%s)", user_id, text, channel_id)
        return Reply(f"`/aipostit` works only in <#{settings.slack_channel_id}>.", public=False)
    return Reply(HELP, public=False)
