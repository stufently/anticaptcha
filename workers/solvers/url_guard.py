"""Single page_url check for every solver that opens a user-supplied URL.

Call validate_page_url() before the browser is started and hand the browser
the URL it RETURNS, never the original string: the result is rebuilt from the
parsed parts, so the browser and this check cannot disagree about the host.

It rejects:

- backslashes, whitespace, control characters anywhere (Chromium strips or
  rewrites them: "http://127.0.0.1\\@1.2.3.4/" goes to 127.0.0.1 there);
- any userinfo ("user:pass@host");
- hostnames outside [a-z0-9.-] (percent-escapes, non-ASCII look-alikes; pass
  IDN hosts in punycode form);
- hosts whose last label is numeric but not a valid IPv4 in the WHATWG sense;
  decimal/octal/hex forms (2130706433, 0x7f.1, 017700000001) are decoded the
  way the browser decodes them and checked as that address;
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
import re
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = ("http", "https")
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_HOST_RE = re.compile(r"^[a-z0-9.-]+$")
_FORBIDDEN_CHARS = re.compile(r"[\\\s\x00-\x1f\x7f]")


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


def _whatwg_ipv4(host: str):
    """Parse host like the WHATWG URL standard does if its last label is
    numeric. Returns IPv4Address, None (not an IPv4 host), or raises
    PageURLRejected (numeric but invalid: the browser would refuse it, we
    refuse too)."""
    labels = host.split(".")
    if labels and labels[-1] == "":
        labels = labels[:-1]
    if not labels:
        return None

    def number(label):
        if label == "":
            return None
        if label[:2] == "0x":
            digits, base = label[2:], 16
            if digits == "":
                return 0
        elif len(label) > 1 and label[0] == "0":
            digits, base = label[1:], 8
        else:
            digits, base = label, 10
        try:
            return int(digits, base)
        except ValueError:
            return None

    if number(labels[-1]) is None:
        return None  # an ordinary domain name
    parts = [number(label) for label in labels]
    if len(parts) > 4 or any(p is None for p in parts):
        raise PageURLRejected(f"host {host!r} is a malformed IPv4 address")
    if any(p > 255 for p in parts[:-1]) or parts[-1] >= 256 ** (5 - len(parts)):
        raise PageURLRejected(f"host {host!r} is an out-of-range IPv4 address")
    value = parts[-1]
    for i, p in enumerate(parts[:-1]):
        value += p * 256 ** (3 - i)
    return ipaddress.IPv4Address(value)


def validate_page_url(url) -> str:
    """Return a normalized, safe-to-open URL or raise PageURLRejected."""
    if not isinstance(url, str) or not url:
        raise PageURLRejected("empty or not a string")
    if _FORBIDDEN_CHARS.search(url):
        raise PageURLRejected("backslash, whitespace or control character in URL")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError as e:
        raise PageURLRejected(f"malformed URL ({e})") from None

    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise PageURLRejected(f"scheme {scheme or '(none)'!r} not allowed, only http/https")
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise PageURLRejected("userinfo (user@host) not allowed")
    if not host:
        raise PageURLRejected("no hostname")

    if parts.netloc.lstrip().startswith("["):
        try:
            if "%" in host:  # zone ids ("fe80::1%eth0"): Python accepts them
                raise ValueError("zone id")
            ip = ipaddress.IPv6Address(host)
        except ValueError:
            raise PageURLRejected(f"host {host!r} is not a valid IPv6 address") from None
        if _blocked_ip(ip):
            raise PageURLRejected(f"address {host} is not public")
        netloc_host = f"[{ip.compressed}]"
    else:
        if not _HOST_RE.match(host):
            raise PageURLRejected(f"host {host!r} has characters outside [a-z0-9.-]")
        ip = _whatwg_ipv4(host)
        if ip is not None:
            if _blocked_ip(ip):
                raise PageURLRejected(f"address {host} ({ip}) is not public")
            netloc_host = str(ip)
        else:
            name = host.rstrip(".")
            if not name or ".." in name:
                raise PageURLRejected(f"host {host!r} is malformed")
            if name == "localhost" or name.endswith(".localhost"):
                raise PageURLRejected(f"host {host!r} is localhost")
            try:
                infos = socket.getaddrinfo(name, port or None, proto=socket.IPPROTO_TCP)
            except (socket.gaierror, UnicodeError) as e:
                raise PageURLRejected(f"cannot resolve {name!r} ({e})") from None
            addresses = {info[4][0] for info in infos}
            if not addresses:
                raise PageURLRejected(f"{name!r} resolves to no address")
            for addr in sorted(addresses):
                # strip IPv6 zone id ("fe80::1%eth0")
                if _blocked_ip(ipaddress.ip_address(addr.split("%", 1)[0])):
                    raise PageURLRejected(f"{name!r} resolves to non-public address {addr}")
            netloc_host = name

    normalized = f"{scheme}://{netloc_host}"
    if port is not None:
        normalized += f":{port}"
    normalized += parts.path or "/"
    if parts.query:
        normalized += f"?{parts.query}"
    if parts.fragment:
        normalized += f"#{parts.fragment}"
    return normalized
