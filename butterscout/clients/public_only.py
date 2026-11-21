"""An HTTPX transport that only connects to public addresses.

The fallback fetches pages that search results point at, and a result can point (directly,
by redirect, or by a DNS answer that changes between checks) at the home network or at the
other containers. Checking URLs is not enough: the check has to happen where the socket is
opened, against the address actually dialed. This module does that: every new connection
resolves its host once, refuses the lot if any address is not public, and dials only the
checked addresses. TLS and the Host header still use the URL's name, and pooled connections
are keyed by that name, so a reused connection is one that already passed the check.

Crawl4AI's browser traffic goes through Crawl4AI's own egress proxy (0.9.6), which refuses
non-global addresses too; its rule is close to this one but not identical (it has no explicit
multicast or site-local IPv6 check).
"""

from __future__ import annotations

import asyncio
import socket
import typing

import httpcore
import httpx
from httpcore import AnyIOBackend

from butterscout.utils.url_safety import blocked_hostname, is_public_address


class PrivateAddressError(ValueError):
    """The page's host is (or resolves to) a local or private address."""

    def __init__(self) -> None:
        super().__init__("Refused a local or private address")


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


class PublicOnlyBackend(httpcore.AsyncNetworkBackend):
    """httpcore network backend: resolve once, refuse any non-public answer, dial the
    checked addresses (the next one only if a dial fails outright)."""

    def __init__(self) -> None:
        self._dialer = AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: typing.Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if blocked_hostname(host.lower().rstrip(".")):
            raise PrivateAddressError()
        try:
            addresses = await _resolve(host, port)
        except socket.gaierror as exc:
            raise httpcore.ConnectError(f"Could not resolve {host}") from exc
        if not addresses or not all(is_public_address(address) for address in addresses):
            raise PrivateAddressError()

        error: httpcore.ConnectError | None = None
        for address in addresses:
            try:
                return await self._dialer.connect_tcp(
                    address, port, timeout, local_address, socket_options
                )
            except httpcore.ConnectError as exc:  # refused / unreachable: try the next one
                error = exc
        assert error is not None
        raise error

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: typing.Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise PrivateAddressError()

    async def sleep(self, seconds: float) -> None:
        await self._dialer.sleep(seconds)


def public_only_transport() -> httpx.AsyncHTTPTransport:
    """HTTPX's own transport with its connection pool rebuilt on PublicOnlyBackend.

    HTTPX 0.28 takes no network backend, so this replaces its private `_pool` with the pool
    it would have built (default TLS context and connection limits) plus the backend. If a
    later HTTPX stops using `_pool`, tests/unit/test_public_only.py fails.
    """
    transport = httpx.AsyncHTTPTransport()
    transport._pool = httpcore.AsyncConnectionPool(
        ssl_context=httpx.create_ssl_context(),
        # HTTPX's DEFAULT_LIMITS (httpx.Limits() alone sets no caps).
        max_connections=100,
        max_keepalive_connections=20,
        keepalive_expiry=5.0,
        network_backend=PublicOnlyBackend(),
    )
    return transport
