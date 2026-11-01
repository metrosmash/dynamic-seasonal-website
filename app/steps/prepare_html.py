from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


DROP_TAGS = {"script", "iframe", "object", "embed", "base"}
URL_ATTRIBUTES = {"href", "src", "poster", "action"}
SAFE_SCHEMES = {"http", "https", "mailto", "tel", "data"}
CSS_URL = re.compile(r"url\(\s*(?P<quote>['\"]?)(?P<url>[^'\")]+)(?P=quote)\s*\)", re.I)


def _absolute_url(value: str, base_url: str, *, allow_data: bool = False) -> str | None:
    value = value.strip()
    if not value or value.startswith("#"):
        return value
    try:
        scheme = urlsplit(value).scheme.lower()
    except ValueError:
        return None
    allowed = SAFE_SCHEMES if allow_data else SAFE_SCHEMES - {"data"}
    if scheme and scheme not in allowed:
        return None
    if scheme in {"mailto", "tel", "data"}:
        return value
    try:
        return urljoin(base_url, value)
    except ValueError:
        return None


def _srcset_items(value: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    index = 0
    while index < len(value):
        while index < len(value) and (value[index].isspace() or value[index] == ","):
            index += 1
        if index >= len(value):
            break
        start = index
        is_data = value[index:index + 5].lower() == "data:"
        while index < len(value) and not value[index].isspace():
            if value[index] == "," and not is_data:
                break
            index += 1
        url = value[start:index].rstrip(",")
        while index < len(value) and value[index].isspace():
            index += 1
        descriptor_start = index
        while index < len(value) and value[index] != ",":
            index += 1
        descriptor = value[descriptor_start:index].strip()
        if index < len(value):
            index += 1
        if url:
            items.append((url, descriptor))
    return items


def _rewrite_css_urls(css: str, base_url: str) -> str:
    def replace(match: re.Match[str]) -> str:
        absolute = _absolute_url(match.group("url"), base_url, allow_data=True)
        if absolute is None:
            return ""
        quote = match.group("quote")
        return f"url({quote}{absolute}{quote})"

    return CSS_URL.sub(replace, css)


def prepare_html(source_html: str, source_url: str) -> str:
    soup = BeautifulSoup(source_html, "html.parser")
    page_base_url = source_url
    base_tag = soup.find("base", href=True)
    if base_tag:
        try:
            candidate = urljoin(source_url, str(base_tag.get("href", "")).strip())
            parsed_candidate = urlsplit(candidate)
        except ValueError:
            pass
        else:
            if parsed_candidate.scheme.lower() in {"http", "https"} and parsed_candidate.netloc:
                page_base_url = candidate
    for tag in soup.find_all(DROP_TAGS):
        tag.decompose()
    for tag in soup.find_all("base"):
        tag.decompose()
    for meta in soup.find_all("meta"):
        if (meta.get("http-equiv") or "").lower() == "refresh":
            meta.decompose()

    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            attr_lower = attr.lower()
            value = tag.attrs[attr]
            if attr_lower.startswith("on") or attr_lower in {"srcdoc", "formaction"}:
                del tag.attrs[attr]
                continue
            if attr_lower in URL_ATTRIBUTES and isinstance(value, str):
                absolute = _absolute_url(
                    value,
                    page_base_url,
                    allow_data=(tag.name == "img" and attr_lower == "src"),
                )
                if absolute is None:
                    del tag.attrs[attr]
                else:
                    tag.attrs[attr] = absolute
            elif attr_lower == "srcset" and isinstance(value, str):
                rewritten = []
                for resource, descriptor in _srcset_items(value):
                    absolute = _absolute_url(resource, page_base_url, allow_data=True)
                    if absolute is not None:
                        rewritten.append(" ".join(part for part in (absolute, descriptor) if part))
                if rewritten:
                    tag.attrs[attr] = ", ".join(rewritten)
                else:
                    del tag.attrs[attr]
            elif attr_lower == "style" and isinstance(value, str):
                tag.attrs[attr] = _rewrite_css_urls(value, page_base_url)
        if tag.name == "style" and tag.string:
            tag.string.replace_with(_rewrite_css_urls(str(tag.string), page_base_url))
        if (
            tag.name == "a"
            and isinstance(tag.get("href"), str)
            and not tag["href"].startswith("#")
            and tag["href"].startswith(("http://", "https://"))
        ):
            tag["target"] = "_blank"
            tag["rel"] = ["noopener", "noreferrer"]

    if soup.html is None:
        wrapper = BeautifulSoup("<!doctype html><html><head></head><body></body></html>", "html.parser")
        wrapper.body.append(soup)
        soup = wrapper
    if soup.head is None:
        head = soup.new_tag("head")
        soup.html.insert(0, head)
    if soup.body is None:
        body = soup.new_tag("body")
        for child in list(soup.html.contents):
            if child is not soup.head:
                body.append(child.extract())
        soup.html.append(body)

    visible_text = soup.body.get_text(" ", strip=True)
    if not visible_text:
        raise ValueError(
            "This page has no readable HTML text. JavaScript-heavy websites are not supported yet."
        )
    return "<!doctype html>\n" + str(soup)
