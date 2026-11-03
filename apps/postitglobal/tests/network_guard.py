"""No test may reach the network. Installed for the whole run by tests/conftest.py.

A test that resolves a hostname or opens a connection to anything but this machine fails
at once with NetworkBlockedError. Without it, a mock that stops applying (an SDK that
switches HTTP clients, as anthropic 2.x did from httpx to httpx2) sends real requests to
real services: #16's tests reached api.anthropic.com and failed on a confusing 401.
Loopback stays open for tests that run a local server (tests/test_metrics.py).
"""

import ipaddress
import socket
from typing import Any

LOCAL_NAMES = frozenset({"localhost"})


class NetworkBlockedError(RuntimeError):
    """A test tried to reach the network. Mock the call: respx for httpx clients."""


def _is_local(host: object) -> bool:
    if not isinstance(host, str):
        return False
    if host in LOCAL_NAMES:
        return True
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    # Loopback, or the "any address" a server binds to (0.0.0.0, ::): neither leaves here.
    return address.is_loopback or address.is_unspecified


_real_getaddrinfo = socket.getaddrinfo
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
    if host is not None and not _is_local(host.decode() if isinstance(host, bytes) else host):
        raise NetworkBlockedError(f"test tried to resolve {host!r}")
    return _real_getaddrinfo(host, *args, **kwargs)


def _check(address: Any) -> None:
    # Unix sockets (a path, not a tuple) stay open: they don't leave the machine.
    if isinstance(address, tuple) and not _is_local(address[0]):
        raise NetworkBlockedError(f"test tried to connect to {address[0]!r}")


def _connect(self: socket.socket, address: Any) -> None:
    _check(address)
    _real_connect(self, address)


def _connect_ex(self: socket.socket, address: Any) -> int:
    _check(address)
    return _real_connect_ex(self, address)


def install() -> None:
    socket.getaddrinfo = _getaddrinfo
    socket.socket.connect = _connect  # type: ignore[method-assign,assignment]
    socket.socket.connect_ex = _connect_ex  # type: ignore[method-assign,assignment]
