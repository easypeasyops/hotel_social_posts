import threading
from typing import Any

import pytest
from slack_bolt.request import BoltRequest
from slack_sdk import WebClient
from slack_sdk.web import SlackResponse

import app.main
from app.commands import HELP
from app.config import Settings

COMMAND = {
    "command": "/aipostit",
    "text": " help ",
    "user_id": "U1",
    "channel_id": "C1",
    "team_id": "T1",
    "response_url": "https://hooks.slack.test/r",
}


def test_run_replies_to_the_person(settings: Settings) -> None:
    said: list[dict[str, Any]] = []
    app.main.run(COMMAND, lambda **kw: said.append(kw), settings)
    assert said == [{"text": HELP, "response_type": "ephemeral"}]


def test_the_slash_command_is_acknowledged_and_run(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran: list[dict[str, Any]] = []
    done = threading.Event()

    def fake_run(command: dict[str, Any], *_: object) -> None:
        ran.append(command)
        done.set()

    monkeypatch.setattr(app.main, "run", fake_run)
    # Bolt checks the bot token (auth.test) before the first listener: Slack answers here.
    bot = {"ok": True, "team_id": "T1", "user_id": "UB", "bot_id": "B1"}
    monkeypatch.setattr(
        WebClient,
        "auth_test",
        lambda self, **_: SlackResponse(
            client=self,
            http_verb="POST",
            api_url="",
            req_args={},
            data=bot,
            headers={},
            status_code=200,
        ),
    )
    bolt = app.main.build(settings, verify_token=False)
    response = bolt.dispatch(BoltRequest(body=COMMAND, mode="socket_mode"))
    assert response.status == 200  # acknowledged; the listener goes on in Bolt's thread
    assert done.wait(5)
    assert [c["text"] for c in ran] == [" help "]


def test_main_connects_with_the_app_token(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[str] = []

    class Handler:
        def __init__(self, bolt: object, token: str) -> None:
            self.token = token

        def start(self) -> None:
            started.append(self.token)

    for key, value in {
        "SLACK_APP_TOKEN": "xapp-1",
        "SLACK_BOT_TOKEN": "xoxb-1",
        "SLACK_TEAM_ID": "T1",
        "SLACK_CHANNEL_ID": "C1",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(app.main, "build", lambda settings: object())
    monkeypatch.setattr(app.main, "SocketModeHandler", Handler)
    app.main.main()
    assert started == ["xapp-1"]
