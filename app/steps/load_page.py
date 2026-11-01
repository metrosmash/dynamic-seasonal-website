from __future__ import annotations

import gzip
import http.client
import ipaddress
import socket
import ssl
from email.message import Message
from urllib.parse import urljoin, urlsplit

from app.steps.validate_input import URLValidationError, validate_public_url


class FetchError(ValueError):
    pass


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, address: str, timeout: int):
        super().__init__(host, port, timeout=timeout)
        self.address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self.address, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, address: str, timeout: int):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self) -> None:
        raw_socket = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)
        except Exception:
            raw_socket.close()
            raise


def _read_bounded(response: http.client.HTTPResponse, max_bytes: int) -> bytes:
    content_encoding = response.getheader("Content-Encoding", "identity").lower().strip()
    if content_encoding in {"", "identity"}:
        body = response.read(max_bytes + 1)
    elif content_encoding == "gzip":
        with gzip.GzipFile(fileobj=response) as decoded:
            body = decoded.read(max_bytes + 1)
    else:
        raise FetchError("The website uses an unsupported content encoding.")
    if len(body) > max_bytes:
        raise FetchError(f"The website is larger than the {max_bytes // (1024 * 1024)} MB page limit.")
    return body


def _request_once(url: str, addresses: list[str], timeout: int, max_bytes: int):
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    hostname = parts.hostname or ""
    try:
        host = hostname.encode("idna").decode("ascii")
        port = parts.port or (443 if scheme == "https" else 80)
    except (UnicodeError, ValueError) as exc:
        raise FetchError("The website URL has an invalid hostname or port.") from exc
    path = parts.path or "/"
    if parts.query:
        path += f"?{parts.query}"
    host_header = f"[{host}]" if ":" in host else host
    if parts.port is not None:
        host_header += f":{parts.port}"

    failures: list[OSError] = []
    for address in addresses:
        try:
            connection_class = _PinnedHTTPSConnection if scheme == "https" else _PinnedHTTPConnection
            connection = connection_class(host, port, address, timeout)
            connection.request(
                "GET",
                path,
                headers={
                    "Host": host_header,
                    "User-Agent": "HalloweenThemePreview/0.1",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Encoding": "gzip, identity",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                response.read(4096)
                connection.close()
                return response.status, location, None, response.getheader("Content-Type", "")
            if response.status < 200 or response.status >= 300:
                response.read(4096)
                connection.close()
                raise FetchError(f"The website returned HTTP {response.status}.")
            content_type = response.getheader("Content-Type", "")
            if response.getheader("Content-Encoding", "").lower() not in {"", "identity", "gzip"}:
                connection.close()
                raise FetchError("The website uses an unsupported content encoding.")
            content_length = response.getheader("Content-Length")
            if content_length and response.getheader("Content-Encoding", "").lower() != "gzip":
                try:
                    parsed_content_length = int(content_length)
                except ValueError:
                    parsed_content_length = 0
                if parsed_content_length > max_bytes:
                    connection.close()
                    raise FetchError(
                        f"The website is larger than the {max_bytes // (1024 * 1024)} MB page limit."
                    )
            body = _read_bounded(response, max_bytes)
            connection.close()
            return response.status, None, body, content_type
        except FetchError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            failures.append(exc)
    if failures:
        last_error = failures[-1]
        if isinstance(last_error, (TimeoutError, socket.timeout)):
            raise FetchError("The website took too long to respond.") from last_error
        raise FetchError("Could not connect to the website.") from last_error
    raise FetchError("Could not connect to the website.")


def _decode_html(body: bytes, content_type: str) -> str:
    header = Message()
    header["content-type"] = content_type
    charset = header.get_content_charset()
    if charset:
        try:
            return body.decode(charset, errors="replace")
        except LookupError:
            pass
    return body.decode("utf-8", errors="replace")


def load_page(
    url: str,
    *,
    timeout: int = 12,
    max_bytes: int = 3 * 1024 * 1024,
    max_redirects: int = 5,
) -> tuple[str, str]:
    current_url = url
    for redirect_number in range(max_redirects + 1):
        try:
            parts, addresses = validate_public_url(current_url)
        except URLValidationError as exc:
            raise FetchError(str(exc)) from exc
        try:
            status, location, body, content_type = _request_once(
                current_url, addresses, timeout, max_bytes
            )
        except (TimeoutError, socket.timeout) as exc:
            raise FetchError("The website took too long to respond.") from exc
        if status in {301, 302, 303, 307, 308}:
            if not location:
                raise FetchError("The website redirected without providing a destination.")
            if redirect_number >= max_redirects:
                raise FetchError("The website redirected too many times.")
            current_url = urljoin(current_url, location)
            continue
        if not content_type.split(";", 1)[0].strip().lower() in {
            "text/html", "application/xhtml+xml"
        }:
            raise FetchError("The URL did not return an HTML page.")
        if body is None:
            raise FetchError("The website returned an empty response.")
        html = _decode_html(body, content_type)
        if not html.strip():
            raise FetchError("The website returned an empty page.")
        return html, current_url
    raise FetchError("The website redirected too many times.")
