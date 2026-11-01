from __future__ import annotations

from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


DROP_TAGS = {"script", "iframe", "object", "embed", "base"}
URL_ATTRIBUTES = {"href", "src", "poster", "action"}
SAFE_SCHEMES = {"http", "https", "mailto", "tel", "data"}


def prepare_html(source_html: str, source_url: str) -> str:
    soup = BeautifulSoup(source_html, "html.parser")
    for tag in soup.find_all(DROP_TAGS):
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
                stripped = value.strip()
                scheme = urlsplit(stripped).scheme.lower()
                allowed_schemes = SAFE_SCHEMES - {"data"}
                if tag.name == "img" and attr_lower == "src":
                    allowed_schemes = SAFE_SCHEMES
                if scheme and scheme not in allowed_schemes:
                    del tag.attrs[attr]
                elif stripped and not stripped.startswith(("#", "data:", "mailto:", "tel:")):
                    tag.attrs[attr] = urljoin(source_url, stripped)
        if tag.name == "a" and tag.get("href", "").startswith(("http://", "https://")):
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
