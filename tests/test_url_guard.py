"""Shared page_url SSRF guard (no network: DNS is always mocked)."""
import socket

import pytest

from workers.solvers import url_guard
from workers.solvers.url_guard import PageURLRejected, validate_page_url


def _fake_resolver(mapping):
    def getaddrinfo(host, port, *args, **kwargs):
        if host not in mapping:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [
            (socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port or 0))
            for a in mapping[host]
        ]
    return getaddrinfo


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    mapping = {
        "example.com": ["93.184.215.14", "2606:2800:21f:cb07:6820:80da:af6b:8b2c"],
        "internal.example": ["10.1.2.3"],
        "mixed.example": ["93.184.215.14", "192.168.1.5"],
    }
    monkeypatch.setattr(url_guard.socket, "getaddrinfo", _fake_resolver(mapping))
    return mapping


@pytest.mark.parametrize("url,reason", [
    ("file:///etc/passwd", "scheme 'file'"),
    ("data:text/html,x", "scheme 'data'"),
    ("javascript:alert(1)", "scheme 'javascript'"),
    ("chrome://settings", "scheme 'chrome'"),
    ("about:blank", "scheme 'about'"),
    ("http://127.0.0.1", "not public"),
    ("http://169.254.169.254/latest/meta-data", "not public"),
    ("http://10.0.0.1", "not public"),
    ("http://100.64.0.1", "not public"),
    ("http://224.0.0.1", "not public"),
    ("http://0.0.0.0", "not public"),
    ("http://[::1]", "not public"),
    ("http://[::ffff:127.0.0.1]", "not public"),
    ("http://localhost", "localhost"),
    ("http://LOCALHOST.:8080", "localhost"),
    ("http://app.localhost", "localhost"),
    ("http:///path-only", "no hostname"),
    ("http://internal.example", "non-public address 10.1.2.3"),
    ("http://mixed.example", "non-public address 192.168.1.5"),
    ("http://does-not-resolve.example", "cannot resolve"),
    ("", "empty"),
    (None, "empty"),
])
def test_rejected(url, reason):
    with pytest.raises(PageURLRejected) as exc:
        validate_page_url(url)
    msg = str(exc.value)
    assert msg.startswith("page_url rejected: ")
    assert reason in msg


@pytest.mark.parametrize("url", [
    "https://example.com",
    "http://example.com:8080/page?x=1",
    "https://93.184.215.14/",
])
def test_allowed(url):
    assert validate_page_url(url) == url


def test_rejection_is_value_error_not_attribute_error():
    # old recaptcha check crashed with AttributeError on hostname None
    with pytest.raises(ValueError):
        validate_page_url("https://")
