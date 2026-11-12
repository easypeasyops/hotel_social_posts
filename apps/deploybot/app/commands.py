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
HELP = "\n".join(
    [
        "`/aipostit status`: which release staging and prod run.",
        "`/aipostit release patch|minor`: opens the version bump PR; it merges once `ci` is green"
        " and the release goes to staging.",
        "`/aipostit promote`: opens the PR giving prod staging's release, for a review in GitHub.",
        "`/aipostit rollback staging|prod`: opens the PR giving it the release before the one it"
        " runs; prod's waits for a review in GitHub.",
    ]
)
# What requested_by may hold in the workflows (they refuse anything else): a Slack name.
NAME = re.compile(r"^[A-Za-z0-9._ -]{1,80}$")


class Repository(Protocol):
    def read_file(self, path: str, ref: str = "main") -> str: ...

    def dispatch(self, workflow: str, inputs: dict[str, str]) -> None: ...


@dataclass(frozen=True)
class Reply:
    text: str
    public: bool  # in the channel for everyone, or only to the person who asked


@dataclass(frozen=True)
class Action:
    """A command that starts a workflow: only for the allowed users."""

    workflow: str
    inputs: dict[str, str]
    what: str  # for the reply: "release patch"
    then: str  # what happens next


def parse(words: list[str]) -> Action | None:
    match words:
        case ["release", ("patch" | "minor") as part]:
            then = "opens the bump PR, which merges once `ci` is green; apply any migration first."
            return Action("bump.yml", {"app": APP, "part": part}, f"release {part}", then)
        case ["promote"]:
            then = "opens the PR giving prod staging's release; it waits for a review in GitHub."
            return Action("promote.yml", {"app": APP}, "promote", then)
        case ["rollback", ("staging" | "prod") as env]:
            then = f"opens the PR giving {env} the release before the one it runs" + (
                "; it waits for a review in GitHub." if env == "prod" else ", which merges itself."
            )
            return Action("rollback.yml", {"app": APP, "env": env}, f"rollback {env}", then)
        case _:
            return None


def handle(
    text: str,
    *,
    user_id: str,
    user_name: str,
    channel_id: str,
    team_id: str,
    settings: Settings,
    repo: Repository,
) -> Reply:
    # In #aipostit-deploys only, so everyone there sees every command.
    if team_id != settings.slack_team_id or channel_id != settings.slack_channel_id:
        log.warning("refused %s: /aipostit %r outside the channel (%s)", user_id, text, channel_id)
        return Reply(f"`/aipostit` works only in <#{settings.slack_channel_id}>.", public=False)
    words = text.split()
    if words == ["status"]:
        try:
            return Reply(status(repo), public=True)
        except httpx.HTTPError:
            log.exception("status: GitHub failed")
            return Reply("I couldn't read the deploy files from GitHub. Try again.", False)
    action = parse(words)
    if action is None:
        return Reply(HELP, public=False)
    if user_id not in settings.allowed_users:
        log.warning("refused %s: /aipostit %r, not an allowed user", user_id, text)
        return Reply(
            f"You can't run `{action.what}`: you aren't on deploybot's allowed users.", False
        )
    inputs = {**action.inputs, "requested_by": user_name if NAME.match(user_name) else user_id}
    url = f"https://github.com/{settings.github_repository}/actions/workflows/{action.workflow}"
    try:
        repo.dispatch(action.workflow, inputs)
    except httpx.HTTPError:
        log.exception("%s: dispatching %s failed", action.what, action.workflow)
        return Reply(f"GitHub didn't start <{url}|{action.workflow}>. Try again.", False)
    log.info("%s started %s with %s", user_id, action.workflow, inputs)
    return Reply(
        f"<@{user_id}> asked for *{action.what}*: <{url}|{action.workflow}> {action.then}", True
    )


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
