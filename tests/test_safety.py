import ipaddress
from urllib.parse import urlparse

import pytest

from safety import (
    UnsafeURLError,
    assert_safe_proxy,
    assert_safe_url,
    resolve_redirect,
)


def test_rejects_non_http_schemes():
    for url in ("file:///etc/passwd", "ftp://example.com/a", "javascript:alert(1)"):
        with pytest.raises(UnsafeURLError):
            assert_safe_url(url)


def test_rejects_loopback_and_metadata():
    for url in (
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://0.0.0.0/",
        "http://169.254.169.254/latest/meta-data",
        "http://localhost/admin",
    ):
        with pytest.raises(UnsafeURLError):
            assert_safe_url(url)


def test_rejects_private_by_default():
    with pytest.raises(UnsafeURLError):
        assert_safe_url("http://192.168.1.20/internal")
    with pytest.raises(UnsafeURLError):
        assert_safe_url("http://10.0.0.8/")


def test_allow_private_permits_rfc1918_and_loopback():
    assert assert_safe_url("http://192.168.1.20/internal", allow_private=True)
    assert assert_safe_url("http://127.0.0.1/status", allow_private=True)


def test_metadata_stays_blocked_even_when_private_allowed():
    with pytest.raises(UnsafeURLError):
        assert_safe_url("http://169.254.169.254/latest/meta-data", allow_private=True)


def test_rejects_embedded_credentials():
    with pytest.raises(UnsafeURLError):
        assert_safe_url("https://user:secret@example.com/path")


def test_public_hostname_allowed(monkeypatch):
    monkeypatch.setattr(
        "safety._hostname_ips",
        lambda hostname, timeout=5.0: [ipaddress.ip_address("93.184.216.34")],
    )
    assert assert_safe_url("https://example.com/shop")


def test_dns_rebinding_blocked(monkeypatch):
    monkeypatch.setattr(
        "safety._hostname_ips",
        lambda hostname, timeout=5.0: [ipaddress.ip_address("127.0.0.1")],
    )
    with pytest.raises(UnsafeURLError):
        assert_safe_url("https://evil.example")


def test_redirect_to_private_blocked():
    with pytest.raises(UnsafeURLError):
        resolve_redirect("https://example.com/a", "http://127.0.0.1/secret")


def test_redirect_relative_stays_on_host(monkeypatch):
    monkeypatch.setattr(
        "safety._hostname_ips",
        lambda hostname, timeout=5.0: [ipaddress.ip_address("93.184.216.34")],
    )
    nxt = resolve_redirect("https://example.com/a", "/b")
    assert urlparse(nxt).path == "/b"


def test_proxy_scheme_validation():
    assert assert_safe_proxy("") == ""
    assert assert_safe_proxy("http://127.0.0.1:8080")
    with pytest.raises(UnsafeURLError):
        assert_safe_proxy("file:///tmp/proxy")
