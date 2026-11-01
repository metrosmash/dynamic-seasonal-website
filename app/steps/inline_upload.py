from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup


HTML_EXTENSIONS = {".html", ".htm"}
IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
CSS_URL = re.compile(r"url\(\s*(?P<quote>['\"]?)(?P<url>[^'\")]+)(?P=quote)\s*\)", re.I)


class UploadError(ValueError):
    pass


@dataclass(frozen=True)
class InlineUploadResult:
    html: str
    source_id: str
    warnings: tuple[str, ...]


def safe_filename(filename: str) -> str:
    normalized = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not normalized or normalized in {".", ".."} or "\x00" in normalized:
        raise UploadError("Each uploaded file must have a valid filename.")
    return normalized


def validate_uploads(
    html_filename: str,
    html_bytes: bytes,
    assets: dict[str, bytes],
    *,
    max_html_bytes: int,
    max_total_bytes: int,
) -> tuple[str, bytes, dict[str, bytes]]:
    html_name = safe_filename(html_filename)
    if not html_name.lower().endswith(tuple(HTML_EXTENSIONS)):
        raise UploadError("Upload an HTML file ending in .html or .htm.")
    if not html_bytes:
        raise UploadError("The uploaded HTML file is empty.")
    if len(html_bytes) > max_html_bytes:
        raise UploadError(f"The HTML file exceeds the {max_html_bytes}-byte limit.")

    validated_assets: dict[str, bytes] = {}
    seen_names = {html_name.casefold()}
    for submitted_name, content in assets.items():
        name = safe_filename(submitted_name)
        extension = _extension(name)
        if extension != ".css" and extension not in IMAGE_MIME_TYPES:
            raise UploadError(
                f"Unsupported file type for {name}. Upload CSS or PNG, JPG, GIF, or WebP assets."
            )
        if name.casefold() in seen_names:
            raise UploadError(f"More than one uploaded file has the name {name}.")
        seen_names.add(name.casefold())
        validated_assets[name] = content

    total_bytes = len(html_bytes) + sum(map(len, validated_assets.values()))
    if total_bytes > max_total_bytes:
        raise UploadError(f"The uploaded files exceed the {max_total_bytes}-byte total limit.")
    return html_name, html_bytes, validated_assets


def _extension(filename: str) -> str:
    return f".{filename.rsplit('.', 1)[-1].lower()}" if "." in filename else ""


def _resource_name(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc:
        return None
    path = unquote(parsed.path.replace("\\", "/"))
    return path.rsplit("/", 1)[-1] or None


def _data_uri(filename: str, content: bytes) -> str:
    mime_type = IMAGE_MIME_TYPES[_extension(filename)]
    return f"data:{mime_type};base64,{base64.b64encode(content).decode('ascii')}"


def _rewrite_css(css: str, assets: dict[str, bytes], matched: set[str], missing: set[str]) -> str:
    by_basename = {name.casefold(): (name, data) for name, data in assets.items()}

    def replace(match: re.Match[str]) -> str:
        value = match.group("url").strip()
        name = _resource_name(value)
        if name is None:
            return match.group(0)
        item = by_basename.get(name.casefold())
        if item is None:
            missing.add(name)
            return match.group(0)
        filename, content = item
        if _extension(filename) not in IMAGE_MIME_TYPES:
            missing.add(name)
            return match.group(0)
        matched.add(filename)
        quote = match.group("quote")
        return f"url({quote}{_data_uri(filename, content)}{quote})"

    return CSS_URL.sub(replace, css)


def inline_upload(
    html_filename: str,
    html_bytes: bytes,
    assets: dict[str, bytes],
    *,
    max_html_bytes: int = 2 * 1024 * 1024,
    max_total_bytes: int = 8 * 1024 * 1024,
) -> InlineUploadResult:
    html_filename, html_bytes, assets = validate_uploads(
        html_filename,
        html_bytes,
        assets,
        max_html_bytes=max_html_bytes,
        max_total_bytes=max_total_bytes,
    )
    try:
        source_html = html_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UploadError("The HTML file must be UTF-8 encoded.") from exc

    digest = hashlib.sha256()
    for name, content in sorted({html_filename: html_bytes, **assets}.items(), key=lambda item: item[0].casefold()):
        encoded_name = name.encode("utf-8")
        digest.update(len(encoded_name).to_bytes(4, "big"))
        digest.update(encoded_name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    source_id = digest.hexdigest()

    soup = BeautifulSoup(source_html, "html.parser")
    by_basename = {name.casefold(): (name, content) for name, content in assets.items()}
    matched: set[str] = set()
    missing: set[str] = set()

    for link in soup.find_all("link", href=True):
        relations = link.get("rel") or []
        if "stylesheet" not in relations:
            continue
        href = str(link.get("href", ""))
        name = _resource_name(href)
        if name is None:
            continue
        item = by_basename.get(name.casefold())
        if item is None or _extension(item[0]) != ".css":
            missing.add(name)
            continue
        filename, content = item
        matched.add(filename)
        stylesheet = soup.new_tag("style")
        for attribute in ("media", "title", "type"):
            if link.has_attr(attribute):
                stylesheet[attribute] = link[attribute]
        stylesheet["data-uploaded-stylesheet"] = filename
        stylesheet.string = _rewrite_css(
            content.decode("utf-8", errors="replace"), assets, matched, missing
        )
        link.replace_with(stylesheet)

    for image in soup.find_all("img", src=True):
        src = str(image.get("src", ""))
        name = _resource_name(src)
        if name is None:
            continue
        item = by_basename.get(name.casefold())
        if item is None:
            missing.add(name)
            continue
        filename, content = item
        if _extension(filename) not in IMAGE_MIME_TYPES:
            missing.add(name)
            continue
        matched.add(filename)
        image["src"] = _data_uri(filename, content)

    for tag in soup.find_all(True):
        inline_style = tag.get("style")
        if isinstance(inline_style, str) and "url(" in inline_style.lower():
            tag["style"] = _rewrite_css(inline_style, assets, matched, missing)
    for stylesheet in soup.find_all("style"):
        if stylesheet.string and "url(" in stylesheet.string.lower():
            stylesheet.string.replace_with(
                _rewrite_css(str(stylesheet.string), assets, matched, missing)
            )

    warnings = tuple(
        f"{name} was referenced but not uploaded."
        for name in sorted(missing, key=str.casefold)
    )
    return InlineUploadResult(str(soup), source_id, warnings)
