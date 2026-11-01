from __future__ import annotations

import ipaddress
import socket
from urllib.parse import SplitResult, urlsplit


class URLValidationError(ValueError):
    pass


def validate_public_url(url: str) -> tuple[SplitResult, list[str]]:
    if (
        not url
        or len(url) > 2048
        or url != url.strip()
        or any(ord(char) < 32 for char in url)
    ):
        raise URLValidationError("Enter a valid public HTTP or HTTPS URL.")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise URLValidationError("The URL contains an invalid host or port.") from exc

    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.hostname:
        raise URLValidationError("Only public HTTP and HTTPS URLs are supported.")
    if parts.username is not None or parts.password is not None:
        raise URLValidationError("URLs containing usernames or passwords are not allowed.")
    if port is not None and port not in {80, 443}:
        raise URLValidationError("Only ports 80 and 443 are allowed.")

    hostname = parts.hostname.rstrip(".")
    try:
        literal = ipaddress.ip_address(hostname)
        addresses = [str(literal)]
    except ValueError:
        try:
            records = socket.getaddrinfo(hostname, port or (443 if scheme == "https" else 80), type=socket.SOCK_STREAM)
        except OSError as exc:
            raise URLValidationError("The website host could not be resolved.") from exc
        addresses = list(dict.fromkeys(record[4][0] for record in records))

    if not addresses:
        raise URLValidationError("The website host did not resolve to an address.")
    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(address)
        except ValueError as exc:
            raise URLValidationError("The website resolved to an invalid network address.") from exc
        mapped_address = (
            parsed_address.ipv4_mapped
            if isinstance(parsed_address, ipaddress.IPv6Address)
            else None
        )
        checked_address = mapped_address or parsed_address
        if not checked_address.is_global:
            raise URLValidationError(
                "This app can only fetch publicly routable websites; private or reserved addresses are blocked."
            )
    return parts, addresses
