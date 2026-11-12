import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest

from app.health import serve


@pytest.fixture
def probe() -> Iterator[tuple[list[bool], str]]:
    """The probe server on a free port, and the switch for "Slack is connected"."""
    connected = [True]
    server = serve(lambda: connected[0], port=0)
    yield connected, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310  # local test server
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def test_healthz_answers_while_the_process_runs(probe: tuple[list[bool], str]) -> None:
    connected, base = probe
    connected[0] = False
    assert _get(f"{base}/healthz") == (200, "ok")


def test_readyz_follows_the_slack_connection(probe: tuple[list[bool], str]) -> None:
    connected, base = probe
    assert _get(f"{base}/readyz") == (200, "ok")
    connected[0] = False
    assert _get(f"{base}/readyz") == (503, "not ready: no Slack connection")


def test_nothing_else_is_served(probe: tuple[list[bool], str]) -> None:
    assert _get(f"{probe[1]}/")[0] == 404
