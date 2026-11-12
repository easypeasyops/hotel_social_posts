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
        self.dispatched: list[tuple[str, dict[str, str]]] = []

    def dispatch(self, workflow: str, inputs: dict[str, str]) -> None:
        if self.fail:
            raise httpx.HTTPStatusError(
                "403", request=httpx.Request("POST", "x"), response=httpx.Response(403)
            )
        self.dispatched.append((workflow, inputs))

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
    user: str = "U1",
    name: str = "emrah",
) -> Reply:
    return handle(
        text,
        user_id=user,
        user_name=name,
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


@pytest.mark.parametrize(
    "text",
    ["", "help", "status now", "deploy prod", "release major", "rollback dev", "promote now"],
)
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


@pytest.mark.parametrize(
    ("text", "workflow", "inputs", "said"),
    [
        ("release patch", "bump.yml", {"app": "aipostit", "part": "patch"}, "apply any migration"),
        ("release minor", "bump.yml", {"app": "aipostit", "part": "minor"}, "bump PR"),
        ("promote", "promote.yml", {"app": "aipostit"}, "waits for a review"),
        ("rollback prod", "rollback.yml", {"app": "aipostit", "env": "prod"}, "waits for a review"),
        (
            "rollback staging",
            "rollback.yml",
            {"app": "aipostit", "env": "staging"},
            "merges itself",
        ),
    ],
)
def test_an_allowed_user_starts_the_workflow_for_all_to_see(
    settings: Settings, text: str, workflow: str, inputs: dict[str, str], said: str
) -> None:
    repo = FakeRepo()
    reply = _run(text, settings, repo)
    assert repo.dispatched == [(workflow, {**inputs, "requested_by": "emrah"})]
    assert reply.public
    assert reply.text.startswith(f"<@U1> asked for *{text}*: <https://github.com/")
    assert f"/actions/workflows/{workflow}|{workflow}>" in reply.text
    assert said in reply.text


def test_anyone_else_is_refused_privately_and_nothing_starts(settings: Settings) -> None:
    repo = FakeRepo()
    reply = _run("rollback prod", settings, repo, user="U9")
    assert not reply.public
    assert "can't run `rollback prod`" in reply.text
    assert repo.dispatched == []


def test_status_needs_no_allowlist(settings: Settings) -> None:
    assert _run("status", settings, user="U9").public


def test_a_name_the_workflows_would_refuse_is_sent_as_the_user_id(settings: Settings) -> None:
    repo = FakeRepo()
    _run("promote", settings, repo, name="ömer @here")
    assert repo.dispatched == [("promote.yml", {"app": "aipostit", "requested_by": "U1"})]


def test_github_refusing_the_dispatch_is_said_privately(settings: Settings) -> None:
    reply = _run("promote", settings, FakeRepo(fail=True))
    assert not reply.public
    assert "GitHub didn't start" in reply.text
