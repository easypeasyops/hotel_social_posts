import pytest

from app.commands import HELP, Reply, handle
from app.config import Settings


def _run(text: str, settings: Settings, *, channel: str = "C1", team: str = "T1") -> Reply:
    return handle(text, user_id="U1", channel_id=channel, team_id=team, settings=settings)


@pytest.mark.parametrize(("channel", "team"), [("C2", "T1"), ("C1", "T2")])
def test_only_our_channel_takes_commands(settings: Settings, channel: str, team: str) -> None:
    reply = _run("status", settings, channel=channel, team=team)
    assert not reply.public
    assert reply.text == "`/aipostit` works only in <#C1>."


@pytest.mark.parametrize("text", ["", "help", "deploy prod"])
def test_in_the_channel_it_answers_with_the_help_privately(settings: Settings, text: str) -> None:
    assert _run(text, settings) == Reply(HELP, public=False)
