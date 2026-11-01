from __future__ import annotations

import re
from urllib.parse import urlencode, urlsplit

from bs4 import BeautifulSoup
from bs4.element import Doctype, Tag

from app.content.decor_catalog import DECORATIONS, SLOTS_BY_TIER, load_decoration_svg
from app.content.themes import APPROVED_FONTS, THEMES, Palette
from app.content.tiers import TIERS


RESET_CONTAINERS = (
    "div, section, article, aside, header, footer, nav, main, table, th, td, "
    "ul, ol, li, blockquote, pre, code, figure, figcaption, details, summary"
)


def _contrast_ratio(first: str, second: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return sum(weight * channel for weight, channel in zip((0.2126, 0.7152, 0.0722), linear))

    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _palette(theme_id: str, intensity: str) -> Palette:
    theme = THEMES[theme_id]
    return theme.light if TIERS[intensity]["palette"] == "light" else theme.dark


def _theme_css(
    theme_id: str,
    intensity: str,
    *,
    accent: str | None = None,
    animated: tuple[str, ...] = (),
) -> str:
    theme = THEMES[theme_id]
    palette = _palette(theme_id, intensity)
    if accent and re.fullmatch(r"#[0-9a-f]{6}", accent, re.I) and _contrast_ratio(accent, palette.bg) >= 3:
        palette = Palette(
            palette.bg, palette.text, palette.muted, palette.link, accent, palette.surface
        )
    heading_font = theme.heading_font if theme.heading_font in APPROVED_FONTS else "Georgia"
    accent_font = theme.accent_font if theme.accent_font in APPROVED_FONTS else heading_font
    heading_selector = ", ".join(
        f"html body h{level}" for level in TIERS[intensity]["heading_levels"]
    )
    reset_selectors = ", ".join(
        f"html body {selector.strip()}" for selector in RESET_CONTAINERS.split(",")
    )
    overlay = (
        "body::before { content: ''; position: fixed; inset: 0; z-index: 2147482998; "
        "pointer-events: none; background: radial-gradient(ellipse at center, transparent 58%, #0005); }"
        if TIERS[intensity]["overlays"] else ""
    )
    animation_rules = {
        "hw-flap": "50% { transform: translateY(-4px) rotate(4deg); }",
        "hw-glow": "50% { filter: drop-shadow(0 0 12px var(--hw-accent)); }",
        "hw-bob": "50% { transform: translateY(-8px); }",
        "hw-sway": "50% { transform: rotate(8deg); }",
        "hw-flicker": "50% { opacity: .78; }",
    }
    keyframes = "\n".join(
        f"@keyframes {name} {{ 0%, 100% {{ }} {animation_rules[name]} }}"
        for name in dict.fromkeys(animated)
        if name in animation_rules
    )
    animations = "\n".join(
        f".{name} {{ animation: {name} {2.4 + index * 0.3}s ease-in-out infinite; }}"
        for index, name in enumerate(dict.fromkeys(animated))
        if name in animation_rules
    )
    return f"""
:root {{
  color-scheme: {"light" if TIERS[intensity]["palette"] == "light" else "dark"};
  --hw-bg: {palette.bg};
  --hw-text: {palette.text};
  --hw-muted: {palette.muted};
  --hw-link: {palette.link};
  --hw-accent: {palette.accent};
  --hw-surface: {palette.surface};
}}
html body {{ background-color: var(--hw-bg) !important; color: var(--hw-text) !important; }}
{reset_selectors} {{ background-color: transparent !important; color: inherit !important; }}
html body .card, html body .infobox, html body .panel, html body [class~="surface"] {{
  background-color: var(--hw-surface) !important; color: var(--hw-text) !important;
}}
html body a, html body a:link {{ color: var(--hw-link) !important; }}
html body a:visited {{ color: {palette.link} !important; }}
{heading_selector} {{
  color: var(--hw-accent) !important;
  font-family: "{heading_font}", Georgia, serif;
}}
{f'html body blockquote {{ font-family: "{accent_font}", Georgia, serif; }}' if intensity == "high" else ""}
.hw-added {{ box-sizing: border-box; pointer-events: none; }}
html body .hw-decoration {{ display: block; width: min(var(--hw-size), 100%); color: var(--hw-accent) !important; }}
.hw-decoration svg {{ display: block; width: 100%; height: auto; overflow: visible; }}
.hw-slot-top-left, .hw-slot-top-right {{
  position: fixed; z-index: 2147483000; top: 1rem; width: min(var(--hw-size), 18vw);
  filter: drop-shadow(0 0 10px color-mix(in srgb, var(--hw-accent), transparent 45%));
}}
.hw-slot-top-left {{ left: 1rem; }}
.hw-slot-top-right {{ right: 1rem; }}
.hw-slot-margin-left, .hw-slot-margin-right {{
  position: fixed; z-index: 2147482999; top: 40%; width: min(var(--hw-size), 10vw);
}}
.hw-slot-margin-left {{ left: .5rem; }}
.hw-slot-margin-right {{ right: .5rem; }}
.hw-slot-header, .hw-slot-footer, .hw-slot-before-h2 {{
  width: min(var(--hw-size), 20vw); margin: .75rem auto; opacity: .92;
}}
.hw-slot-float {{
  position: fixed; z-index: 2147482999; left: 2vw; top: 38%; width: min(var(--hw-size), 12vw);
}}
html body .hw-banner {{
  margin: 0 auto 1rem; padding: .65rem 1rem; width: fit-content; max-width: 100%;
  border: 1px solid var(--hw-accent); border-radius: .65rem;
  background: var(--hw-surface) !important; color: var(--hw-text) !important; text-align: center;
  font: 700 1rem/1.4 "{heading_font}", Georgia, serif;
}}
.hw-attribution {{ margin: 1rem auto; padding: .5rem 1rem; text-align: center; font-size: .85rem; }}
@media (max-width: 900px) {{
  .hw-slot-margin-left, .hw-slot-margin-right {{ display: none; }}
}}
@media (max-width: 600px) {{
  .hw-slot-top-left, .hw-slot-top-right {{ width: min(42px, 12vw); opacity: .75; }}
}}
@media (prefers-reduced-motion: no-preference) {{
  {keyframes}
  {animations}
}}
@media (prefers-reduced-motion: reduce) {{
  .hw-decoration {{ animation: none !important; transition: none !important; }}
}}
{overlay}
""".strip()


def _font_stylesheet(soup: BeautifulSoup, theme_id: str) -> None:
    theme = THEMES[theme_id]
    families = [
        font for font in dict.fromkeys((theme.heading_font, theme.accent_font))
        if font in APPROVED_FONTS
    ]
    if not families:
        return
    link = soup.new_tag(
        "link",
        rel="stylesheet",
        href="https://fonts.googleapis.com/css2?" + urlencode(
            [("family", font) for font in families] + [("display", "swap")]
        ),
        attrs={"data-hw-added": "fonts"},
    )
    soup.head.append(link)


def _decoration_node(soup: BeautifulSoup, name: str, slot: str, animation: str) -> Tag:
    entry = DECORATIONS[name]
    slot_name = slot.split(":", 1)[0]
    svg = load_decoration_svg(name)
    node = BeautifulSoup(
        f'<div class="hw-added hw-decoration hw-slot-{slot_name} {animation}" '
        f'data-hw-added="decoration" aria-hidden="true">{svg}</div>',
        "html.parser",
    ).div
    node["data-hw-slot"] = slot
    node["style"] = f'--hw-size: {entry["size"]}px'
    return node


def _supported_placements(
    placements: tuple[tuple[str, str], ...],
    intensity: str,
) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    for name, slot in placements:
        if name not in DECORATIONS:
            continue
        slot_name = slot.split(":", 1)[0]
        if slot_name not in DECORATIONS[name]["slots"] or slot_name not in SLOTS_BY_TIER[intensity]:
            continue
        if (slot_name == "before-h2") != (":" in slot):
            continue
        if slot_name == "before-h2":
            try:
                if int(slot.split(":", 1)[1]) < 1:
                    continue
            except (IndexError, ValueError):
                continue
        result.append((name, slot))
        if len(result) >= TIERS[intensity]["max_decorations"]:
            break
    return tuple(result)


def assemble_page(
    source_html: str,
    *,
    source_url: str,
    theme_id: str,
    intensity: str,
    placements: tuple[tuple[str, str], ...],
    accent: str | None = None,
) -> str:
    soup = BeautifulSoup(source_html, "html.parser")
    for element in list(soup.contents):
        if isinstance(element, Doctype):
            element.extract()
    if soup.html is None:
        wrapper = BeautifulSoup("<!doctype html><html><head></head><body></body></html>", "html.parser")
        wrapper.body.append(soup)
        soup = wrapper
    if soup.head is None:
        soup.html.insert(0, soup.new_tag("head"))
    if soup.body is None:
        soup.html.append(soup.new_tag("body"))

    placements = _supported_placements(placements, intensity)
    style = soup.new_tag("style", attrs={"data-hw-added": "theme"})
    animated: list[str] = []
    animation_cap = TIERS[intensity]["animations"]
    for name, _ in placements:
        animation = DECORATIONS[name]["animation"]
        if animation and animation not in animated and len(animated) < animation_cap:
            animated.append(animation)
    style.string = _theme_css(
        theme_id, intensity, accent=accent, animated=tuple(animated)
    )
    soup.head.append(style)
    _font_stylesheet(soup, theme_id)

    if TIERS[intensity]["banner"]:
        banner = soup.new_tag("aside", attrs={
            "class": "hw-added hw-banner",
            "data-hw-added": "banner",
            "aria-label": "Halloween decoration",
        })
        banner.string = THEMES[theme_id].banner
        first_h1 = soup.body.find("h1")
        if first_h1:
            first_h1.insert_before(banner)
        else:
            soup.body.insert(0, banner)

    limited_placements = placements[:TIERS[intensity]["max_decorations"]]
    assigned_animations: list[str] = []
    animation_count = 0
    for name, _ in limited_placements:
        animation = DECORATIONS[name]["animation"]
        if animation and animation_count < animation_cap:
            assigned_animations.append(animation)
            animation_count += 1
        else:
            assigned_animations.append("")
    for placement_index, (name, slot) in enumerate(limited_placements):
        if name not in DECORATIONS or slot.split(":", 1)[0] not in DECORATIONS[name]["slots"]:
            continue
        animation_class = assigned_animations[placement_index]
        node = _decoration_node(soup, name, slot, animation_class)
        slot_name = slot.split(":", 1)[0]
        if slot_name in {"top-left", "top-right", "margin-left", "margin-right", "float"}:
            soup.body.insert(0, node)
        elif slot_name == "header":
            heading = soup.body.find("h1")
            if heading:
                heading.insert_after(node)
            else:
                soup.body.insert(0, node)
        elif slot_name == "footer":
            soup.body.append(node)
        elif slot_name == "before-h2":
            try:
                heading_index = int(slot.split(":", 1)[1])
            except (IndexError, ValueError):
                continue
            headings = soup.body.find_all("h2")
            if 1 <= heading_index <= len(headings):
                headings[heading_index - 1].insert_before(node)

    attribution = soup.new_tag("p", attrs={
        "class": "hw-added hw-attribution",
        "data-hw-added": "attribution",
    })
    if source_url:
        attribution.append("Decorated version of ")
        source_link = soup.new_tag("a", href=source_url, target="_blank", rel="noopener noreferrer")
        source_link.string = source_url
        attribution.append(source_link)
    else:
        attribution.string = "Decorated version of uploaded website files."
    source_host = (urlsplit(source_url).hostname or "").lower()
    if source_host.endswith(".wikipedia.org") or source_host == "wikipedia.org":
        attribution.append(" · Wikipedia content is available under ")
        license_link = soup.new_tag(
            "a",
            href="https://creativecommons.org/licenses/by-sa/4.0/",
            target="_blank",
            rel="noopener noreferrer",
        )
        license_link.string = "CC BY-SA 4.0"
        attribution.append(license_link)
    soup.body.append(attribution)
    return "<!doctype html>\n" + str(soup)
