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
    # parser differentials (Chromium/WHATWG vs urlsplit)
    ("http://127.0.0.1:8000\\@93.184.215.14/", "backslash"),
    ("http://93.184.215.14\\.127.0.0.1/", "backslash"),
    ("http://example.com/\\..\\x", "backslash"),
    (" http://example.com/", "whitespace"),
    ("http://example.com/ ", "whitespace"),
    ("http://exa\tmple.com/", "whitespace"),
    ("http://example.com\n.127.0.0.1/", "whitespace"),
    ("http://example.com/\x00", "control"),
    ("http://user:pw@example.com/", "userinfo"),
    ("http://@example.com/", "userinfo"),
    ("http://93.184.215.14@127.0.0.1/", "userinfo"),
    ("http://%31%32%37.0.0.1/", "outside [a-z0-9.-]"),
    ("http://\uff11\uff12\uff17.0.0.1/", "outside [a-z0-9.-]"),
    ("http://2130706433/", "(127.0.0.1) is not public"),
    ("http://0x7f.1/", "(127.0.0.1) is not public"),
    ("http://017700000001/", "(127.0.0.1) is not public"),
    ("http://0177.0.0.1/", "(127.0.0.1) is not public"),
    ("http://127.1/", "(127.0.0.1) is not public"),
    ("http://127.0.0.1./", "(127.0.0.1) is not public"),
    ("http://0xa9fea9fe/", "(169.254.169.254) is not public"),
    ("http://0/", "(0.0.0.0) is not public"),
    ("http://1.2.3.4.5/", "malformed IPv4"),
    ("http://example.123/", "malformed IPv4"),
    ("http://256.0.0.1/", "out-of-range IPv4"),
    ("http://4294967296/", "out-of-range IPv4"),
    ("http://[fe80::1%25eth0]/", "not a valid IPv6"),
    ("http://example.com:99999/", "malformed URL"),
])
def test_rejected(url, reason):
    with pytest.raises(PageURLRejected) as exc:
        validate_page_url(url)
    msg = str(exc.value)
    assert msg.startswith("page_url rejected: ")
    assert reason in msg


@pytest.mark.parametrize("url,normalized", [
    ("https://example.com", "https://example.com/"),
    ("http://example.com:8080/page?x=1#top", "http://example.com:8080/page?x=1#top"),
    ("HTTPS://EXAMPLE.COM./a", "https://example.com/a"),
    ("https://93.184.215.14/", "https://93.184.215.14/"),
    # numeric forms of a public address are decoded and rewritten dotted
    ("http://1572394766/", "http://93.184.215.14/"),
    ("http://0x5d.0xb8.0xd7.0x0e/", "http://93.184.215.14/"),
    ("http://[2606:2800:21f:cb07:6820:80da:af6b:8b2c]/", "http://[2606:2800:21f:cb07:6820:80da:af6b:8b2c]/"),
])
def test_allowed_returns_normalized(url, normalized):
    assert validate_page_url(url) == normalized


def test_numeric_hosts_never_reach_the_resolver(monkeypatch):
    """glibc getaddrinfo also decodes 2130706433 to 127.0.0.1; the verdict must
    come from our own IPv4 decoding, not depend on the resolver."""
    def boom(*a, **k):
        raise AssertionError("resolver must not be called for numeric hosts")
    monkeypatch.setattr(url_guard.socket, "getaddrinfo", boom)
    for url in ("http://2130706433/", "http://0x7f.1/", "http://017700000001/"):
        with pytest.raises(PageURLRejected, match="not public"):
            validate_page_url(url)


def test_rejection_is_value_error_not_attribute_error():
    # old recaptcha check crashed with AttributeError on hostname None
    with pytest.raises(ValueError):
        validate_page_url("https://")
