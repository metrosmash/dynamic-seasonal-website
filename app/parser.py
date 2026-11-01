from __future__ import annotations

import html.parser
import re
from dataclasses import dataclass
from typing import Any


TIERS = {
    "low": {"decorations": 3, "css_chars": 0, "palette": "light"},
    "medium": {"decorations": 8, "css_chars": 2500, "palette": "dark"},
    "high": {"decorations": 16, "css_chars": 6000, "palette": "dark"},
}

DECORATIONS = {
    "bat": {"top-left", "top-right", "header", "margin-left", "margin-right", "float"},
    "cobweb": {"top-left", "top-right", "footer"},
    "pumpkin": {"before-h2", "footer", "margin-left", "margin-right"},
    "ghost": {"margin-left", "margin-right", "before-h2", "float"},
    "spider": {"top-left", "top-right", "header"},
    "moon": {"top-right", "header"},
    "tombstone": {"footer", "before-h2"},
    "candle": {"margin-left", "margin-right", "footer"},
    "crow": {"header", "margin-right"},
    "bone-divider": {"before-h2"},
}

THEMES = {
    "haunted-library",
    "graveyard-fog",
    "witchs-kitchen",
    "pumpkin-patch",
    "blood-moon",
    "cobweb-attic",
    "midnight-carnival",
    "spooky-forest",
    "vampire-lounge",
    "ghost-ship",
}

ALLOWED_SLOTS = {
    "low": {"top-left", "top-right", "header"},
    "medium": {
        "top-left", "top-right", "header", "before-h2", "footer",
        "margin-left", "margin-right",
    },
    "high": set().union(*DECORATIONS.values()),
}


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
        issues.append("invalid theme line")
        theme = None
    else:
        theme = theme_value.lower() if theme_value else None
        if theme and theme not in THEMES:
            issues.append("unknown theme")

    accent_values = re.findall(r"^\s*ACCENT:\s*(.*?)\s*$", design_lines, re.I | re.M)
    accent_value = unquote(accent_values[-1]) if accent_values else ""
    if accent_values and not re.fullmatch(r"#[0-9a-f]{6}", accent_value, re.I):
        issues.append("invalid accent line")
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
            issues.append("malformed placement")
            continue
        name, slot = match.group(1).lower(), match.group(2).lower()
        slot_name = slot.split(":", 1)[0]
        if name not in DECORATIONS or slot_name not in DECORATIONS[name]:
            issues.append("unknown decoration or slot")
        elif slot_name not in ALLOWED_SLOTS[effective_tier]:
            issues.append("placement exceeds tier")
        else:
            placements.append((name, slot))

    if len(placements) > budget["decorations"]:
        issues.append("decoration count exceeds tier")
    if len(css) > budget["css_chars"]:
        issues.append("CSS exceeds tier budget")

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
