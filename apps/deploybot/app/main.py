"""deploybot: the `/aipostit` slash command over Slack's Socket Mode, an outbound WebSocket,
so Slack needs no way in to the laptop cluster. `python -m app.main`."""

import logging
import os
from collections.abc import Callable
from typing import Any

from slack_bolt import Ack, App, Respond
from slack_bolt.adapter.socket_mode import SocketModeHandler

from app.commands import Repository, handle
from app.config import Settings
from app.github import GitHub
from app.health import serve

log = logging.getLogger(__name__)


def run(
    command: dict[str, Any], respond: Callable[..., Any], settings: Settings, repo: Repository
) -> None:
    text = command.get("text", "").strip()
    try:
        reply = handle(
            text,
            user_id=command["user_id"],
            user_name=command.get("user_name", ""),
            channel_id=command["channel_id"],
            team_id=command["team_id"],
            settings=settings,
            repo=repo,
        )
    except Exception:
        # Whatever broke, the person hears so; Slack would otherwise say the app didn't respond.
        log.exception("%s ran /aipostit %r: failed", command["user_id"], text)
        respond(
            text=f"`/aipostit {text}` failed: deploybot's log has the error.",
            response_type="ephemeral",
        )
        return
    log.info("%s ran /aipostit %r", command["user_id"], text)
    respond(text=reply.text, response_type="in_channel" if reply.public else "ephemeral")


def build(settings: Settings, repo: Repository, *, verify_token: bool = True) -> App:
    app = App(token=settings.slack_bot_token, token_verification_enabled=verify_token)

    @app.command("/aipostit")
    def aipostit(ack: Ack, command: dict[str, Any], respond: Respond) -> None:
        ack()  # within Slack's 3 seconds; the reply follows through the response URL
        run(command, respond, settings, repo)

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env(os.environ)
    repo = GitHub(
        settings.github_app_client_id,
        settings.github_app_installation_id,
        settings.github_app_private_key,
        settings.github_repository,
    )
    handler = SocketModeHandler(build(settings, repo), settings.slack_app_token)
    serve(handler.client.is_connected)
    handler.start()  # type: ignore[no-untyped-call]  # slack_bolt leaves it unannotated


if __name__ == "__main__":
    main()
