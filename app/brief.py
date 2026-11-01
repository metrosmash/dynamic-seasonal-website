from __future__ import annotations

from typing import Any

from app.content.themes import THEMES
from app.parser import ALLOWED_SLOTS, DECORATIONS, TIERS


def build_prompt(
    summary: dict[str, Any],
    tier: str,
    theme_id: str = "pumpkin-patch",
) -> str:
    budget = TIERS[tier]
    theme = THEMES[theme_id]
    palette = theme.light if budget["palette"] == "light" else theme.dark
    catalog = "\n".join(
        f"- {name}: {', '.join(sorted(slots & ALLOWED_SLOTS[tier]))}"
        for name, slots in sorted(DECORATIONS.items())
        if slots & ALLOWED_SLOTS[tier]
    )
    headings = "\n".join(
        f"- h{level}: {text}" for level, text in summary["headings"]
    ) or "- (no headings found)"
    example = f"""THEME: {theme.id}
ACCENT: {palette.accent}
PLACE: bat @ top-right"""
    if tier != "low":
        example += """
PLACE: pumpkin @ before-h2:2"""
    if budget["css_chars"]:
        example += """
CSS:
h1 { letter-spacing: 0.04em; }"""

    before_h2_rule = (
        "- For before-h2 placements, use an integer such as before-h2:2.\n"
        if tier != "low" else ""
    )
    css_rule = (
        "- Low intensity has no model CSS; omit CSS.\n"
        if tier == "low"
        else "- Keep any suggested CSS within the stated character budget.\n"
    )
    return f"""You choose Halloween decorations for an existing web page. You do not write HTML.

Assigned theme: {theme.id} - {theme.description}.
Intensity: {tier}
Palette: {budget['palette']}
Budget: at most {budget['decorations']} decorations and at most {budget['css_chars']} characters of CSS.
The catalog below contains only slots allowed at this intensity.

Decoration catalog and allowed slots:
{catalog}

Page summary:
- Title: {summary['title']}
- Approximate word count: {summary['word_count']}
- h2 count: {summary['h2_count']}
Headings:
{headings}

Rules:
- Repeat the assigned theme exactly; do not choose a different theme.
- Do not hide, move, resize, or add text to existing content.
- Use only catalog decorations and allowed slots.
{before_h2_rule.rstrip()}
- Do not use fixed or absolute positioning except on .hw- classes.
- Use only --hw-bg, --hw-text, --hw-link, --hw-accent, and --hw-surface CSS variables.
{css_rule.rstrip()}

Output format:
{example}

Output only the labelled lines and optional CSS. Do not include HTML."""
