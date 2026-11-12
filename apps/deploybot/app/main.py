"""deploybot: the `/aipostit` slash command over Slack's Socket Mode, an outbound WebSocket,
so Slack needs no way in to the laptop cluster. `python -m app.main`."""

import logging
import os
from collections.abc import Callable
from typing import Any

from slack_bolt import Ack, App, Respond
from slack_bolt.adapter.socket_mode import SocketModeHandler

from app.commands import handle
from app.config import Settings

log = logging.getLogger(__name__)


def run(command: dict[str, Any], respond: Callable[..., Any], settings: Settings) -> None:
    text = command.get("text", "").strip()
    reply = handle(
        text,
        user_id=command["user_id"],
        channel_id=command["channel_id"],
        team_id=command["team_id"],
        settings=settings,
    )
    log.info("%s ran /aipostit %r", command["user_id"], text)
    respond(text=reply.text, response_type="in_channel" if reply.public else "ephemeral")


def build(settings: Settings, *, verify_token: bool = True) -> App:
    app = App(token=settings.slack_bot_token, token_verification_enabled=verify_token)

    @app.command("/aipostit")
    def aipostit(ack: Ack, command: dict[str, Any], respond: Respond) -> None:
        ack()  # within Slack's 3 seconds; the reply follows through the response URL
        run(command, respond, settings)

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env(os.environ)
    handler = SocketModeHandler(build(settings), settings.slack_app_token)
    handler.start()  # type: ignore[no-untyped-call]  # slack_bolt leaves it unannotated


if __name__ == "__main__":
    main()
