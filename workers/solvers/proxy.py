"""Validate client proxies and pin their public address before Chromium uses it."""
import ipaddress
import re
import socket
from typing import Optional
from urllib.parse import unquote, urlsplit

from workers.solvers.url_guard import _blocked_ip


def parse_proxy(value) -> Optional[dict]:
    """Return Playwright proxy options; errors never contain client input."""
    if value is None:
        return None
    if not isinstance(value, str) or not value or re.search(r'[\\\s\x00-\x1f\x7f]', value):
        raise ValueError('proxy must be a URL string without whitespace or control characters')
    try:
        parts = urlsplit(value)
        host, port = parts.hostname, parts.port
        username, password = parts.username, parts.password
    except ValueError:
        raise ValueError('malformed proxy URL') from None
    if parts.scheme not in ('http', 'https', 'socks5'):
        raise ValueError('proxy scheme must be http, https or socks5')
    if not host or port is None or not 1 <= port <= 65535:
        raise ValueError('proxy requires a host and port between 1 and 65535')
    if parts.path or parts.query or parts.fragment:
        raise ValueError('proxy URL must not contain a path, query or fragment')
    if username is not None or password is not None:
        if parts.scheme == 'socks5' and username:
            raise ValueError('socks5 proxy with credentials is not supported')
        if not username or not password:
            raise ValueError('proxy requires both username and password')
        username, password = unquote(username), unquote(password)

    name = host.rstrip('.')
    if name == 'localhost' or name.endswith('.localhost'):
        raise ValueError('proxy host must be public')
    # Zone identifiers and escaped hostnames have no place in a public proxy.
    if '%' in host:
        raise ValueError('invalid proxy host')
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        if not re.fullmatch(r'[a-z0-9.-]+', name) or '..' in name:
            raise ValueError('invalid proxy host') from None
        try:
            infos = socket.getaddrinfo(name, port, proto=socket.IPPROTO_TCP)
            addresses = [ipaddress.ip_address(addr.split('%', 1)[0])
                         for addr in sorted({info[4][0] for info in infos})]
        except (OSError, UnicodeError, ValueError):
            raise ValueError('cannot resolve proxy host') from None
    if not addresses or any(_blocked_ip(ip) for ip in addresses):
        raise ValueError('proxy host must resolve only to public addresses')
    ip = addresses[0]
    server_host = f'[{ip}]' if ip.version == 6 else str(ip)
    result = {'server': f'{parts.scheme}://{server_host}:{port}'}
    if username is not None:
        result.update(username=username, password=password)
    return result
