"""What `/aipostit <text>` does: who may run it, and the reply. Slack-free, so it is tested
without Slack; app/main.py hands it each command."""

import logging
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import Settings

log = logging.getLogger(__name__)

APP = "aipostit"
ENVS = ("staging", "prod")
# The line .github/scripts/deploy-pr.sh writes: digest: "sha256:…" # aipostit vX.Y.Z[, …]
DIGEST_LINE = re.compile(
    r'^  digest: "(?P<digest>sha256:[0-9a-f]{64})"(?: # [a-z0-9-]+ v(?P<version>\d+\.\d+\.\d+))?',
    re.MULTILINE,
)
HELP = "`/aipostit status`: which release staging and prod run."


class Repository(Protocol):
    def read_file(self, path: str, ref: str = "main") -> str: ...


@dataclass(frozen=True)
class Reply:
    text: str
    public: bool  # in the channel for everyone, or only to the person who asked


def handle(
    text: str, *, user_id: str, channel_id: str, team_id: str, settings: Settings, repo: Repository
) -> Reply:
    # In #aipostit-deploys only, so everyone there sees every command.
    if team_id != settings.slack_team_id or channel_id != settings.slack_channel_id:
        log.warning("refused %s: /aipostit %r outside the channel (%s)", user_id, text, channel_id)
        return Reply(f"`/aipostit` works only in <#{settings.slack_channel_id}>.", public=False)
    match text.split():
        case ["status"]:
            try:
                return Reply(status(repo), public=True)
            except httpx.HTTPError:
                log.exception("status: GitHub failed")
                return Reply("I couldn't read the deploy files from GitHub. Try again.", False)
        case _:
            return Reply(HELP, public=False)


def running(values: str) -> str:
    """The release an env file names, or a short digest when its line names none."""
    match = DIGEST_LINE.search(values)
    if match is None:
        return "no image"
    if match["version"]:
        return f"v{match['version']}"
    return f"`{match['digest'][:19]}`"


def status(repo: Repository) -> str:
    staging, prod = (running(repo.read_file(f"apps/{APP}/deploy/envs/{env}.yaml")) for env in ENVS)
    return (
        f"*{APP}*: staging runs *{staging}*, prod runs *{prod}* "
        "(the digests on main, which Argo CD deploys)."
    )
