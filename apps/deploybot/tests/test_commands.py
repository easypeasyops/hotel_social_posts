import httpx
import pytest

from app.commands import HELP, Reply, handle, running
from app.config import Settings

STAGING = 'environment: staging\nimage:\n  digest: "sha256:{}" # aipostit v0.5.3\n'.format("a" * 64)
PROD = 'environment: prod\nimage:\n  digest: "sha256:{}" # aipostit v0.5.2, as staging\n'.format(
    "b" * 64
)


class FakeRepo:
    def __init__(self, files: dict[str, str] | None = None, fail: bool = False) -> None:
        self.files = files or {
            "apps/aipostit/deploy/envs/staging.yaml": STAGING,
            "apps/aipostit/deploy/envs/prod.yaml": PROD,
        }
        self.fail = fail

    def read_file(self, path: str, ref: str = "main") -> str:
        if self.fail:
            raise httpx.ConnectError("down")
        assert ref == "main"
        return self.files[path]


def _run(
    text: str,
    settings: Settings,
    repo: FakeRepo | None = None,
    *,
    channel: str = "C1",
    team: str = "T1",
) -> Reply:
    return handle(
        text,
        user_id="U1",
        channel_id=channel,
        team_id=team,
        settings=settings,
        repo=repo or FakeRepo(),
    )


def test_status_says_what_each_env_runs_for_everyone(settings: Settings) -> None:
    reply = _run("status", settings)
    assert reply.public
    assert "staging runs *v0.5.3*, prod runs *v0.5.2*" in reply.text


@pytest.mark.parametrize(("channel", "team"), [("C2", "T1"), ("C1", "T2")])
def test_only_our_channel_takes_commands(settings: Settings, channel: str, team: str) -> None:
    reply = _run("status", settings, channel=channel, team=team)
    assert not reply.public
    assert reply.text == "`/aipostit` works only in <#C1>."


@pytest.mark.parametrize("text", ["", "help", "status now", "deploy prod"])
def test_anything_else_gets_the_help_privately(settings: Settings, text: str) -> None:
    assert _run(text, settings).text == HELP
    assert not _run(text, settings).public


def test_github_failing_is_said_privately(settings: Settings) -> None:
    reply = _run("status", settings, FakeRepo(fail=True))
    assert not reply.public
    assert "couldn't read" in reply.text


@pytest.mark.parametrize(
    ("values", "shown"),
    [
        (STAGING, "v0.5.3"),
        (STAGING.replace(" # aipostit v0.5.3", ""), "`sha256:aaaaaaaaaaaa`"),  # a hand edit
        ("environment: prod\n", "no image"),
    ],
)
def test_running_reads_the_digest_line(values: str, shown: str) -> None:
    assert running(values) == shown
