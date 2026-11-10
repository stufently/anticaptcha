"""Single page_url check for every solver that opens a user-supplied URL.

Call validate_page_url() before the browser is started. It rejects:

- schemes other than http/https (file:, data:, chrome:, javascript:, about: ...);
- URLs without a hostname;
- localhost and *.localhost;
- IP literals in private, loopback, link-local, CGNAT (100.64.0.0/10),
  reserved, multicast or unspecified ranges (IPv4-mapped IPv6 included);
- hostnames for which ANY resolved address falls into those ranges, and
  hostnames that do not resolve at all.

Limitation: the name is resolved here and again by the browser, so DNS
rebinding (a name that answers with a public address now and a private one a
moment later) is not closed by this check. Egress from the worker must also
be restricted at the network level (e.g. a Kubernetes NetworkPolicy).
"""
import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = ("http", "https")
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


class PageURLRejected(ValueError):
    """page_url failed the SSRF check."""

    def __init__(self, reason: str):
        super().__init__(f"page_url rejected: {reason}")


def _blocked_ip(ip) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or (ip.version == 4 and ip in _CGNAT)
    )


def validate_page_url(url) -> str:
    """Return url unchanged if it is safe to open, else raise PageURLRejected."""
    if not isinstance(url, str) or not url.strip():
        raise PageURLRejected("empty or not a string")
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname
        port = parts.port
    except ValueError as e:
        raise PageURLRejected(f"malformed URL ({e})") from None

    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise PageURLRejected(f"scheme {scheme or '(none)'!r} not allowed, only http/https")
    if not host:
        raise PageURLRejected("no hostname")

    host = host.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise PageURLRejected(f"host {host!r} is localhost")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _blocked_ip(literal):
            raise PageURLRejected(f"address {host} is not public")
        return url

    try:
        infos = socket.getaddrinfo(host, port or None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as e:
        raise PageURLRejected(f"cannot resolve {host!r} ({e})") from None
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise PageURLRejected(f"{host!r} resolves to no address")
    for addr in sorted(addresses):
        # strip IPv6 zone id ("fe80::1%eth0")
        if _blocked_ip(ipaddress.ip_address(addr.split("%", 1)[0])):
            raise PageURLRejected(f"{host!r} resolves to non-public address {addr}")
    return url
