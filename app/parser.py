from __future__ import annotations

import html.parser
import re
from dataclasses import dataclass
from typing import Any

from app.content.decor_catalog import DECORATIONS as DECORATION_CATALOG
from app.content.decor_catalog import SLOTS_BY_TIER
from app.content.themes import THEMES as THEME_CATALOG
from app.content.tiers import TIERS as TIER_CATALOG

TIERS = {
    name: {
        "decorations": tier["max_decorations"],
        "css_chars": tier["css_chars"],
        "palette": tier["palette"],
    }
    for name, tier in TIER_CATALOG.items()
}
DECORATIONS = {name: item["slots"] for name, item in DECORATION_CATALOG.items()}
THEMES = set(THEME_CATALOG)
ALLOWED_SLOTS = SLOTS_BY_TIER


class PageSummaryParser(html.parser.HTMLParser):
    """Extract a deterministic page title and heading summary."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.headings: list[tuple[int, str]] = []
        self._active: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title" or (len(tag) == 2 and tag[0] == "h" and tag[1].isdigit()):
            self._active = tag
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._active:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != self._active:
            return
        text = " ".join(" ".join(self._text).split())
        if tag == "title":
            self.title = text[:120]
        elif len(self.headings) < 15:
            self.headings.append((int(tag[1]), text[:60]))
        self._active = None
        self._text = []


@dataclass(frozen=True)
class DesignResult:
    theme: str | None
    accent: str | None
    placements: tuple[tuple[str, str], ...]
    css: str
    issues: tuple[str, ...]

    @property
    def compliant(self) -> bool:
        return bool(self.placements) and not self.issues


def parse_design_response(text: str, tier: str) -> DesignResult:
    """Parse the model's line-based design response and validate its choices."""
    issues: list[str] = []
    if not isinstance(text, str):
        return DesignResult(None, None, (), "", ("input must be text",))
    if tier not in TIERS:
        issues.append("unknown intensity")
    effective_tier = tier if tier in TIERS else "medium"
    budget = TIERS[effective_tier]

    css_marker = re.search(r"^\s*CSS:\s*$", text, re.I | re.M)
    design_lines = text[:css_marker.start()] if css_marker else text
    css = ""
    if css_marker:
        css = text[css_marker.end():]
        css = "\n".join(
            line for line in css.splitlines()
            if not re.fullmatch(r"\s*(```|~~~)(?:css)?\s*", line, re.I)
        ).strip()
        css = css[:budget["css_chars"]]

    def unquote(value: str) -> str:
        value = value.strip()
        quote_pairs = {'"': '"', "'": "'", "“": "”", "‘": "’"}
        closing_quote = quote_pairs.get(value[:1])
        if closing_quote and value.endswith(closing_quote):
            return value[1:-1].strip()
        return value

    theme_values = re.findall(r"^\s*THEME:\s*(.*?)\s*$", design_lines, re.I | re.M)
    theme_value = unquote(theme_values[-1]) if theme_values else ""
    if theme_values and not re.fullmatch(r"[a-z0-9-]+", theme_value, re.I):
        theme = None
    else:
        theme = theme_value.lower() if theme_value else None
        if theme and theme not in THEMES:
            theme = None

    accent_values = re.findall(r"^\s*ACCENT:\s*(.*?)\s*$", design_lines, re.I | re.M)
    accent_value = unquote(accent_values[-1]) if accent_values else ""
    if accent_values and not re.fullmatch(r"#[0-9a-f]{6}", accent_value, re.I):
        accent = None
    else:
        accent = accent_value.lower() if accent_value else None

    placements: list[tuple[str, str]] = []
    placement_lines = re.findall(r"^\s*PLACE:(.*)$", design_lines, re.I | re.M)
    for line in placement_lines:
        line = unquote(line)
        match = re.fullmatch(
            r"\s*([a-z-]+)\s*@\s*([a-z0-9-]+(?::\d+)?)\s*",
            line,
            re.I,
        )
        if not match:
            continue
        name, slot = match.group(1).lower(), match.group(2).lower()
        slot_name = slot.split(":", 1)[0]
        if (slot_name == "before-h2") != (":" in slot):
            continue
        if slot_name == "before-h2":
            heading_number = slot.split(":", 1)[1]
            try:
                if len(heading_number) > 6 or int(heading_number) < 1:
                    continue
            except ValueError:
                continue
        if name not in DECORATIONS or slot_name not in DECORATIONS[name]:
            continue
        elif slot_name not in ALLOWED_SLOTS[effective_tier]:
            continue
        else:
            placements.append((name, slot))

    placements = placements[:budget["decorations"]]

    return DesignResult(theme, accent, tuple(placements), css, tuple(issues))


def summarize_html(text: str, fallback_title: str = "page") -> dict[str, Any]:
    parser = PageSummaryParser()
    parser.feed(text)
    return {
        "title": parser.title or fallback_title,
        "byte_size": len(text.encode("utf-8")),
        "word_count": len(re.findall(r"\b[\w'-]+\b", re.sub(r"<[^>]*>", " ", text))),
        "headings": parser.headings,
        "h2_count": sum(level == 2 for level, _ in parser.headings),
    }
