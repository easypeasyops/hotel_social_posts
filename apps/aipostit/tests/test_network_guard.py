"""The guard itself: the network is closed to tests, this machine is not."""

import socket

import httpx
import pytest

from tests.network_guard import NetworkBlockedError


def test_a_request_to_a_real_service_fails_at_once() -> None:
    # What #16's Claude tests did once the mock stopped applying.
    with pytest.raises(NetworkBlockedError, match="api.anthropic.com"):
        httpx.get("https://api.anthropic.com/v1/messages")


def test_an_address_is_blocked_as_well_as_a_name() -> None:
    with pytest.raises(NetworkBlockedError, match="1.1.1.1"), socket.socket() as s:
        s.connect(("1.1.1.1", 443))


def test_this_machine_stays_open() -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        with socket.create_connection(server.getsockname(), timeout=1):
            pass
    assert socket.getaddrinfo("localhost", 80)
