"""URL, proxy, and response-size guards for the web scraper.

Blocks non-HTTP(S) schemes, localhost, link-local/metadata addresses, and
(by default) RFC1918 private ranges to reduce SSRF risk when a URL comes
from CLI args or a config file.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urljoin, urlparse

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PROXY_SCHEMES = {"http", "https", "socks5", "socks5h"}
BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.google.com",
    "instance-data",
}

# Cloud instance metadata endpoints frequently used in SSRF payloads.
METADATA_NETS = (
    ipaddress.ip_network("169.254.169.254/32"),
    ipaddress.ip_network("fd00:ec2::254/128"),
)


class UnsafeURLError(ValueError):
    """Raised when a URL is not allowed as a scrape target."""


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        return default


def max_response_bytes() -> int:
    return max(1024, _env_int("SCRAPER_MAX_BYTES", 5_000_000))


def max_redirects() -> int:
    return max(0, _env_int("SCRAPER_MAX_REDIRECTS", 5))


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, *, allow_private: bool) -> bool:
    if any(ip in net for net in METADATA_NETS):
        return True
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    if allow_private:
        return False
    return bool(ip.is_loopback or ip.is_link_local or ip.is_private)


def _hostname_ips(hostname: str, timeout: float = 5.0) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError as exc:
        raise UnsafeURLError(f"Cannot resolve host {hostname!r}: {exc}") from exc
    finally:
        socket.setdefaulttimeout(previous)

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        raw = info[4][0]
        try:
            addresses.append(ipaddress.ip_address(raw))
        except ValueError:
            continue
    if not addresses:
        raise UnsafeURLError(f"Host {hostname!r} resolved to no usable addresses")
    return addresses


def assert_safe_url(url: str, *, allow_private: bool = False) -> str:
    """Validate *url* and return a normalized string, or raise UnsafeURLError."""
    if not url or not isinstance(url, str):
        raise UnsafeURLError("URL is required")

    candidate = url.strip()
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError("Only http and https URLs are allowed")
    if not parsed.hostname:
        raise UnsafeURLError("URL is missing a hostname")
    if parsed.username or parsed.password:
        raise UnsafeURLError("URLs with embedded credentials are not allowed")
    if parsed.port is not None and not (1 <= parsed.port <= 65535):
        raise UnsafeURLError("URL port is invalid")

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in BLOCKED_HOSTNAMES and not allow_private:
        raise UnsafeURLError(f"Host {hostname!r} is not allowed")

    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        if _ip_is_blocked(literal_ip, allow_private=allow_private):
            raise UnsafeURLError(f"Address {hostname} is not allowed")
        return candidate

    for ip in _hostname_ips(hostname):
        if _ip_is_blocked(ip, allow_private=allow_private):
            raise UnsafeURLError(f"Host {hostname!r} resolves to a blocked address")
    return candidate


def resolve_redirect(current_url: str, location: str, *, allow_private: bool = False) -> str:
    if not location or not location.strip():
        raise UnsafeURLError("Redirect response is missing a Location header")
    nxt = urljoin(current_url, location.strip())
    return assert_safe_url(nxt, allow_private=allow_private)


def assert_safe_proxy(proxy_url: str) -> str:
    if not proxy_url or not proxy_url.strip():
        return ""
    parsed = urlparse(proxy_url.strip())
    if parsed.scheme.lower() not in ALLOWED_PROXY_SCHEMES:
        raise UnsafeURLError("Proxy URL must use http, https, socks5, or socks5h")
    if not parsed.hostname:
        raise UnsafeURLError("Proxy URL is missing a hostname")
    return proxy_url.strip()
