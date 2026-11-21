"""The fallback connects only to public addresses: directly, after redirects, after DNS
changes. These run the real fallback client and HTTPX; only DNS and the socket are fake."""

from __future__ import annotations

import socket
import ssl
import typing

import httpcore
import httpx
import pytest

import butterscout.clients.public_only as public_only
from butterscout.clients.public_only import PrivateAddressError
from butterscout.clients.trafilatura_client import TrafilaturaClient
from butterscout.config import Settings
from butterscout.utils.url_safety import is_obviously_unsafe_url, is_public_address

PUBLIC_A = "93.184.216.34"
PUBLIC_B = "93.184.216.35"
PRIVATE = "10.0.0.5"


@pytest.mark.parametrize(
    ("address", "public"),
    [
        (PUBLIC_A, True),
        ("2606:4700::1111", True),
        ("10.0.0.1", False),
        ("192.168.1.1", False),
        ("127.0.0.1", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),  # carrier-grade NAT
        ("0.0.0.0", False),
        ("224.0.0.1", False),  # multicast: Python calls it global
        ("ff0e::1", False),  # IPv6 multicast: same
        ("::1", False),
        ("::", False),
        ("fd00::1", False),
        ("fe80::1", False),
        ("fec0::1", False),  # deprecated site-local: Python calls it global
        ("::ffff:10.0.0.1", False),  # IPv4-mapped
        ("64:ff9b::a00:1", False),  # NAT64 of 10.0.0.1: Python calls it global
        ("64:ff9b::5db8:d822", True),  # NAT64 of a public IPv4
        ("::a00:1", False),  # deprecated IPv4-compatible
        ("2002:a00:1::", False),  # 6to4
    ],
)
def test_public_address_rule(address: str, public: bool) -> None:
    assert is_public_address(address) is public


def test_search_filter_uses_the_same_rule() -> None:
    assert is_obviously_unsafe_url("http://[64:ff9b::a00:1]/")
    assert is_obviously_unsafe_url("http://224.0.0.1/")
    assert not is_obviously_unsafe_url(f"http://{PUBLIC_A}/")


def _response(status: int = 200, headers: str = "", body: bytes = b"") -> bytes:
    head = f"HTTP/1.1 {status} X\r\nContent-Length: {len(body)}\r\n{headers}\r\n"
    return head.encode() + body


PAGE = _response(
    headers="Content-Type: text/html; charset=utf-8\r\n",
    body=b"<html><body><article><p>" + b"Plenty of ordinary prose here. " * 20 + b"</p>"
    b"</article></body></html>",
)


class _Stream(httpcore.AsyncMockStream):
    def __init__(self, buffer: list[bytes], log: dict[str, typing.Any]) -> None:
        super().__init__(buffer)
        self._log = log

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._log["sent"] = self._log.get("sent", b"") + buffer

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.AsyncNetworkStream:
        self._log["tls_hostname"] = server_hostname
        return self


class _Network:
    """Fake DNS and sockets. Records every lookup and every dial."""

    def __init__(self, dns: dict[str, list[str]], pages: dict[str, list[bytes]]) -> None:
        self.dns = dns
        self.pages = pages
        self.unreachable: set[str] = set()
        self.lookups: list[str] = []
        self.dials: list[tuple[str, int]] = []
        self.streams: list[_Stream] = []
        self.log: dict[str, typing.Any] = {}

    async def resolve(self, host: str, port: int) -> list[str]:
        self.lookups.append(host)
        return list(self.dns[host])

    async def connect_tcp(
        self, host: str, port: int, *args: typing.Any, **kwargs: typing.Any
    ) -> httpcore.AsyncNetworkStream:
        self.dials.append((host, port))
        if host in self.unreachable:
            raise httpcore.ConnectError("unreachable")
        stream = _Stream(list(self.pages[host]), self.log)
        self.streams.append(stream)
        return stream


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> _Network:
    """Patches the real dialer class, so even a client that lost the guard (and so uses
    HTTPX's stock backend) never opens a socket."""
    net = _Network({}, {})

    async def dial(
        _backend: object, host: str, port: int, *args: typing.Any, **kwargs: typing.Any
    ) -> httpcore.AsyncNetworkStream:
        return await net.connect_tcp(host, port)

    monkeypatch.setattr(public_only, "_resolve", net.resolve)
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", dial)
    return net


async def _fetch(settings: Settings, url: str) -> str:
    client = TrafilaturaClient(settings)
    await client.connect()
    try:
        return await client._fetch(url)
    finally:
        await client.disconnect()


async def test_public_page_keeps_its_name_for_tls_and_host(
    settings: Settings, network: _Network
) -> None:
    network.dns = {"public.test": [PUBLIC_A]}
    network.pages = {PUBLIC_A: [PAGE]}
    html = await _fetch(settings, "https://public.test/page")
    assert "ordinary prose" in html
    assert network.dials == [(PUBLIC_A, 443)]
    assert network.log["tls_hostname"] == "public.test"
    assert b"Host: public.test\r\n" in network.log["sent"]


async def test_redirect_into_a_private_address_is_refused_before_dialing(
    settings: Settings, network: _Network
) -> None:
    network.dns = {"public.test": [PUBLIC_A], "private.test": [PRIVATE]}
    network.pages = {PUBLIC_A: [_response(302, "Location: http://private.test/admin\r\n")]}
    with pytest.raises(PrivateAddressError):
        await _fetch(settings, "http://public.test/")
    assert network.lookups == ["public.test", "private.test"]
    assert network.dials == [(PUBLIC_A, 80)]


async def test_redirect_between_public_hosts_still_works(
    settings: Settings, network: _Network
) -> None:
    network.dns = {"public.test": [PUBLIC_A], "other.test": [PUBLIC_B]}
    network.pages = {
        PUBLIC_A: [_response(301, "Location: http://other.test/page\r\n")],
        PUBLIC_B: [PAGE],
    }
    assert "ordinary prose" in await _fetch(settings, "http://public.test/")
    assert network.dials == [(PUBLIC_A, 80), (PUBLIC_B, 80)]


@pytest.mark.parametrize(
    "answer",
    [[PRIVATE], [PUBLIC_A, PRIVATE], ["::1"], ["64:ff9b::a00:1"], []],
)
async def test_any_non_public_answer_refuses_the_host(
    settings: Settings, network: _Network, answer: list[str]
) -> None:
    network.dns = {"searxng": answer}
    with pytest.raises(PrivateAddressError):
        await _fetch(settings, "http://searxng:8080/")
    assert network.dials == []


@pytest.mark.parametrize("url", ["http://localhost:8000/", "http://router.local./"])
async def test_local_names_are_refused_without_a_lookup(
    settings: Settings, network: _Network, url: str
) -> None:
    with pytest.raises(PrivateAddressError):
        await _fetch(settings, url)
    assert network.lookups == []
    assert network.dials == []


async def test_literal_private_ip_is_refused(settings: Settings, network: _Network) -> None:
    network.dns = {"169.254.169.254": ["169.254.169.254"]}
    with pytest.raises(PrivateAddressError):
        await _fetch(settings, "http://169.254.169.254/latest/meta-data/")
    assert network.dials == []


async def test_next_checked_address_is_tried_when_one_is_unreachable(
    settings: Settings, network: _Network
) -> None:
    network.dns = {"public.test": [PUBLIC_A, PUBLIC_B]}
    network.pages = {PUBLIC_B: [PAGE]}
    network.unreachable = {PUBLIC_A}
    assert "ordinary prose" in await _fetch(settings, "http://public.test/")
    assert network.lookups == ["public.test"]  # resolved once, never re-resolved
    assert network.dials == [(PUBLIC_A, 80), (PUBLIC_B, 80)]


async def test_a_new_connection_rechecks_a_changed_dns_answer(
    settings: Settings, network: _Network, monkeypatch: pytest.MonkeyPatch
) -> None:
    network.dns = {"rebind.test": [PUBLIC_A]}
    network.pages = {PUBLIC_A: [_response(302, "Location: /again\r\nConnection: close\r\n")]}
    original = network.resolve

    async def rebinding(host: str, port: int) -> list[str]:
        answer = await original(host, port)
        network.dns[host] = [PRIVATE]  # the next lookup answers private
        return answer

    monkeypatch.setattr(public_only, "_resolve", rebinding)
    with pytest.raises(PrivateAddressError):
        await _fetch(settings, "http://rebind.test/")
    assert network.dials == [(PUBLIC_A, 80)]


async def test_unresolvable_host_is_a_fetch_error(
    settings: Settings, network: _Network, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail(host: str, port: int) -> list[str]:
        raise socket.gaierror("no such host")

    monkeypatch.setattr(public_only, "_resolve", fail)
    with pytest.raises(httpx.ConnectError):
        await _fetch(settings, "http://nowhere.test/")


async def test_proxy_environment_cannot_route_around_the_check(
    settings: Settings, network: _Network, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HTTP_PROXY", f"http://{PRIVATE}:3128")
    monkeypatch.setenv("ALL_PROXY", f"http://{PRIVATE}:3128")
    network.dns = {"public.test": [PUBLIC_A]}
    network.pages = {PUBLIC_A: [PAGE]}
    assert "ordinary prose" in await _fetch(settings, "http://public.test/")
    assert network.dials == [(PUBLIC_A, 80)]


async def test_redirect_to_another_scheme_is_not_followed(
    settings: Settings, network: _Network
) -> None:
    network.dns = {"public.test": [PUBLIC_A]}
    network.pages = {PUBLIC_A: [_response(302, "Location: file:///etc/passwd\r\n")]}
    with pytest.raises(httpx.UnsupportedProtocol):
        await _fetch(settings, "http://public.test/")
    assert network.dials == [(PUBLIC_A, 80)]


async def test_pool_keeps_httpx_connection_limits(settings: Settings, network: _Network) -> None:
    hosts = [f"site{i}.test" for i in range(25)]
    network.dns = {host: [f"93.184.216.{i}"] for i, host in enumerate(hosts)}
    network.pages = {f"93.184.216.{i}": [PAGE] for i in range(25)}
    client = TrafilaturaClient(settings)
    await client.connect()
    try:
        for host in hosts:
            await client._fetch(f"http://{host}/")
        assert len(network.dials) == 25
        assert sum(not stream._closed for stream in network.streams) == 20  # idle cap
    finally:
        await client.disconnect()
